"""The idempotent seed (docs/DATA_MODEL.md §9).

``mdt seed`` loads the vocabulary metadata and terms from ``codebook/*.yaml``, then the
organisations and projects from ``seed/projects.yaml``. Rows are matched by
``vocabulary`` + ``code`` (terms) or by the immutable ``seed_key`` (entities, deleted
rows included). Each seeded entity is one write unit on channel ``seed``. Values that a
person set, cleared, restored or verified are never overwritten; such differences are
reported as seed drift. A second run writes nothing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.config import Settings
from mdt.db.models import Organization, Project, Vocabulary, VocabularyTerm
from mdt.db.session import read_transaction, session_settings, write_transaction
from mdt.domain import derived
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import DomainError
from mdt.domain.fieldmeta import seed_may_overwrite
from mdt.domain.normalize import is_empty, values_equal
from mdt.domain.records import Row, field_meta_of, load_links, load_row, stored_values
from mdt.domain.registry import ENTITY_TYPES, EntityTypeSpec
from mdt.domain.vocab import CodebookError, VocabularyFile, load_vocabulary_files
from mdt.domain.writes import WriteUnit, create_record, normalize_changes, update_record

SEED_FILE = "projects.yaml"
_SEED_SECTIONS = (("organizations", "organization"), ("projects", "project"))


class SeedFileError(ValueError):
    """``seed/projects.yaml`` is malformed."""


@dataclass(frozen=True)
class DriftLine:
    """A seed value that differs from a protected (human-set) value."""

    entity_type: str
    key: str
    field: str
    current: Any
    seed: Any

    def __str__(self) -> str:
        return (
            f"seed drift: {self.entity_type} {self.key} · {self.field}: "
            f"current {self.current!r}, seed {self.seed!r}"
        )


@dataclass
class SeedReport:
    """What a seed run did (or, with ``dry_run``, would do)."""

    dry_run: bool = False
    vocabularies_created: int = 0
    vocabularies_updated: int = 0
    created: Counter[str] = field(default_factory=Counter)
    updated: Counter[str] = field(default_factory=Counter)
    unchanged: Counter[str] = field(default_factory=Counter)
    skipped_deleted: Counter[str] = field(default_factory=Counter)
    revisions: int = 0
    drift: list[DriftLine] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    derived_recomputed: bool = False

    def lines(self) -> list[str]:
        """A human-readable summary (for the CLI)."""
        prefix = "would " if self.dry_run else ""
        result = [
            f"vocabularies: {prefix}create {self.vocabularies_created}, "
            f"{prefix}update {self.vocabularies_updated}"
        ]
        for entity_type in ("vocabulary_term", "organization", "project"):
            result.append(
                f"{entity_type}: {prefix}create {self.created[entity_type]}, "
                f"{prefix}update {self.updated[entity_type]}, "
                f"unchanged {self.unchanged[entity_type]}, "
                f"skipped (deleted) {self.skipped_deleted[entity_type]}"
            )
        if not self.dry_run:
            result.append(f"revisions written: {self.revisions}")
            if self.derived_recomputed:
                result.append("derived values recomputed")
        result.extend(str(line) for line in self.drift)
        result.extend(f"error: {error}" for error in self.errors)
        return result


@dataclass(frozen=True)
class SeedFile:
    """Content of ``seed/projects.yaml``."""

    provenance: str | None
    sections: Mapping[str, list[dict[str, Any]]]


def load_seed_file(path: Path) -> SeedFile:
    """Read and check ``seed/projects.yaml``."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SeedFileError(f"cannot read {path.name}") from exc
    if not isinstance(data, dict):
        raise SeedFileError(f"{path.name}: expected a mapping")
    sections: dict[str, list[dict[str, Any]]] = {}
    for key, entity_type in _SEED_SECTIONS:
        entries = data.get(key) or []
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise SeedFileError(f"{path.name}: {key} must be a list of mappings")
        spec = ENTITY_TYPES[entity_type]
        for entry in entries:
            if not entry.get("slug"):
                raise SeedFileError(f"{path.name}: every entry in {key} needs a slug")
            unknown = [name for name in entry if not spec.has_field(name)]
            if unknown:
                raise SeedFileError(f"{path.name}: unknown fields {sorted(unknown)} in {key}")
        sections[entity_type] = entries
    provenance = data.get("provenance")
    return SeedFile(provenance=str(provenance) if provenance else None, sections=sections)


def run_seed(
    session: Session, settings: Settings | None = None, *, dry_run: bool = False
) -> SeedReport:
    """Run the whole seed: vocabularies, organisations, projects, then derived values."""
    settings = settings or session_settings(session)
    report = SeedReport(dry_run=dry_run)
    seed_vocabularies(session, load_vocabulary_files(settings.codebook_path), report)
    seed_file = load_seed_file(settings.seed_path / SEED_FILE)
    for _, entity_type in _SEED_SECTIONS:
        for entry in seed_file.sections[entity_type]:
            seed_entity(session, ENTITY_TYPES[entity_type], entry, seed_file.provenance, report)
    if not dry_run:
        with write_transaction(session):
            report.derived_recomputed = derived.ensure_current(session, utc_now(), settings)
    return report


def seed_vocabularies(
    session: Session, vocabularies: list[VocabularyFile], report: SeedReport
) -> None:
    """Upsert vocabulary metadata (no revisions) and seed every term."""
    with (read_transaction if report.dry_run else write_transaction)(session):
        for vocabulary in vocabularies:
            values = {
                "label": vocabulary.label,
                "description": vocabulary.description,
                "multi": vocabulary.multi,
                "fixed_codes": vocabulary.fixed_codes,
                "source_file": vocabulary.source_file,
            }
            row = session.get(Vocabulary, vocabulary.name)
            if row is None:
                report.vocabularies_created += 1
                if not report.dry_run:
                    session.add(Vocabulary(name=vocabulary.name, **values))
            elif any(getattr(row, key) != value for key, value in values.items()):
                report.vocabularies_updated += 1
                if not report.dry_run:
                    for key, value in values.items():
                        setattr(row, key, value)
        if not report.dry_run:
            session.flush()
    spec = ENTITY_TYPES["vocabulary_term"]
    for vocabulary in vocabularies:
        note = f"Loaded from codebook/{vocabulary.source_file}"
        for term in vocabulary.terms:
            entry = {"vocabulary": vocabulary.name, **term}
            seed_entity(session, spec, entry, note, report)


def _find_term(session: Session, entry: Mapping[str, Any]) -> str | None:
    return session.execute(
        select(VocabularyTerm.id).where(
            VocabularyTerm.vocabulary == entry["vocabulary"], VocabularyTerm.code == entry["code"]
        )
    ).scalar()


def _find_by_seed_key(
    model: type[Project] | type[Organization],
) -> Callable[[Session, Mapping[str, Any]], str | None]:
    def find(session: Session, entry: Mapping[str, Any]) -> str | None:
        return session.execute(select(model.id).where(model.seed_key == entry["slug"])).scalar()

    return find


_FINDERS: dict[str, Callable[[Session, Mapping[str, Any]], str | None]] = {
    "vocabulary_term": _find_term,
    "project": _find_by_seed_key(Project),
    "organization": _find_by_seed_key(Organization),
}


def _entry_key(spec: EntityTypeSpec, entry: Mapping[str, Any]) -> str:
    if spec.name == "vocabulary_term":
        return f"{entry['vocabulary']}:{entry['code']}"
    return str(entry["slug"])


def seed_entity(
    session: Session,
    spec: EntityTypeSpec,
    entry: Mapping[str, Any],
    note: str | None,
    report: SeedReport,
) -> None:
    """Create or update one seeded record in its own write unit (errors are reported)."""
    key = _entry_key(spec, entry)
    try:
        with (read_transaction if report.dry_run else write_transaction)(session):
            unit = WriteUnit.open(session, spec, Actor.seed())
            entity_id = _FINDERS[spec.name](session, entry)
            provided = {name: value for name, value in entry.items() if not is_empty(value)}
            if spec.name != "vocabulary_term":
                provided["seed_key"] = entry["slug"]
            if entity_id is None:
                values = normalize_changes(unit, provided, creating=True)
                report.created[spec.name] += 1
                if not report.dry_run:
                    create_record(unit, values, note=note, batch_id=None)
                    report.revisions += 1
                return
            row = load_row(session, spec, entity_id)
            assert row is not None
            _seed_update(unit, row, provided, note, key, report)
    except (DomainError, CodebookError) as exc:
        details = getattr(exc, "details", None)
        report.errors.append(f"{spec.name} {key}: {exc}" + (f" {details}" if details else ""))


def _seed_update(
    unit: WriteUnit,
    row: Row,
    provided: Mapping[str, Any],
    note: str | None,
    key: str,
    report: SeedReport,
) -> None:
    spec = unit.spec
    if row["deleted_at"] is not None:
        report.skipped_deleted[spec.name] += 1
        return
    updatable = {
        name: value
        for name, value in provided.items()
        if not spec.field(name).create_only and not spec.field(name).internal
    }
    values = normalize_changes(unit, updatable, creating=False)
    links = load_links(unit.session, [row["id"]])[row["id"]] if spec.has_field("links") else None
    current = stored_values(spec, row, links)
    meta = field_meta_of(spec, row)
    changes: dict[str, Any] = {}
    for name, value in values.items():
        if is_empty(value) or values_equal(spec.field(name), current[name], value):
            continue
        if seed_may_overwrite(meta.get(name)):
            changes[name] = value
        else:
            report.drift.append(DriftLine(spec.name, key, name, current[name], value))
    if "in_paper_scope" in changes and "scope_note" not in changes:
        # The scope rule needs the reason in the same change; keep the current one.
        changes["scope_note"] = current["scope_note"]
    if not changes:
        report.unchanged[spec.name] += 1
        return
    report.updated[spec.name] += 1
    if report.dry_run:
        return
    result = update_record(unit, row, changes, note=note, batch_id=None)
    if result.changed:
        report.revisions += 1
