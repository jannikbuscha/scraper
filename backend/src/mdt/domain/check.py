"""Integrity report (docs/DATA_MODEL.md §13, ``mdt check``). It never changes anything."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from mdt.config import Settings
from mdt.db.ddl import REVISION_TRIGGER_NAMES, existing_revision_triggers
from mdt.db.models import (
    Derived,
    Document,
    DocumentLink,
    DocumentText,
    Evidence,
    FetchLog,
    Proposal,
    RawSnapshot,
    Revision,
    SearchKey,
    SourceObservation,
)
from mdt.db.session import read_transaction, session_settings
from mdt.domain import derived
from mdt.domain.normalize import canonical_json, is_empty
from mdt.domain.records import field_meta_of, load_links, state_of, table_of, tracked_values
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.snapshots import diff_fields

_MAX_PER_KIND = 50


@dataclass
class CheckReport:
    """Problems found by :func:`run_check`."""

    problems: list[str] = field(default_factory=list)
    entities_checked: int = 0

    @property
    def ok(self) -> bool:
        """True if nothing was found."""
        return not self.problems


class _Collector:
    def __init__(self, report: CheckReport) -> None:
        self.report = report
        self.counts: dict[str, int] = {}

    def add(self, kind: str, message: str) -> None:
        count = self.counts.get(kind, 0) + 1
        self.counts[kind] = count
        if count <= _MAX_PER_KIND:
            self.report.problems.append(f"{kind}: {message}")
        elif count == _MAX_PER_KIND + 1:
            self.report.problems.append(f"{kind}: … more problems of this kind")


def run_check(session: Session, settings: Settings | None = None) -> CheckReport:
    """Run every check; the report lists what was found."""
    settings = settings or session_settings(session)
    report = CheckReport()
    collector = _Collector(report)
    with read_transaction(session):
        existing = _all_ids(session)
        report.entities_checked = len(existing)
        _check_triggers(session, collector)
        _check_references(session, existing, collector)
        _check_fts(session, existing, collector)
        _check_derived(session, settings, collector)
        _check_revisions(session, collector)
        _check_verifications(session, collector)
        _check_acquisition_references(session, existing, collector)
        _check_merges(session, existing, collector)
    return report


def _all_ids(session: Session) -> dict[str, str]:
    ids: dict[str, str] = {}
    for spec in ENTITY_TYPES.values():
        for entity_id in session.execute(select(table_of(spec).c.id)).scalars():
            ids[entity_id] = spec.name
    return ids


def _check_triggers(session: Session, collector: _Collector) -> None:
    present = existing_revision_triggers(session.connection())
    for name in REVISION_TRIGGER_NAMES:
        if name not in present:
            collector.add("trigger", f"append-only trigger {name} on revision is missing")


def _check_references(session: Session, existing: dict[str, str], collector: _Collector) -> None:
    for spec in ENTITY_TYPES.values():
        table = table_of(spec)
        for ref_field in spec.stored_fields:
            if ref_field.type != "ref":
                continue
            column = table.c[ref_field.name]
            for entity_id, value in session.execute(
                select(table.c.id, column).where(column.is_not(None))
            ):
                if value not in existing:
                    collector.add(
                        "reference", f"{entity_id}.{ref_field.name} refers to missing {value}"
                    )
                elif ref_field.ref_types and existing[value] not in ref_field.ref_types:
                    collector.add(
                        "reference", f"{entity_id}.{ref_field.name} refers to a {existing[value]}"
                    )
    for document_id, subject_id in session.execute(
        select(DocumentLink.document_id, DocumentLink.subject_id)
    ):
        if subject_id not in existing:
            collector.add("reference", f"link of {document_id} refers to missing {subject_id}")
    derived_refs = (
        Derived.entity_id,
        Derived.launch_event_id,
        Derived.existed_by_event_id,
        Derived.trajectory_event_id,
        Derived.portfolio_entry_participation_id,
    )
    for row in session.execute(select(*derived_refs)):
        for attribute, value in zip(derived_refs, row, strict=True):
            if value is not None and value not in existing:
                collector.add(
                    "reference", f"derived.{attribute.key} of {row[0]} refers to missing {value}"
                )
    for (entity_id,) in session.execute(select(Revision.entity_id).distinct()):
        if entity_id not in existing:
            collector.add("reference", f"revisions refer to missing {entity_id}")


def _rowids(session: Session, table: str) -> set[int]:
    return {int(rowid) for (rowid,) in session.execute(text(f"SELECT rowid FROM {table}"))}


def _check_fts(session: Session, existing: dict[str, str], collector: _Collector) -> None:
    keys = {
        entity_id: (int(rowid), entity_type)
        for rowid, entity_id, entity_type in session.execute(
            select(SearchKey.rowid, SearchKey.entity_id, SearchKey.entity_type)
        )
    }
    entity_rows = _rowids(session, "fts_entity")
    document_rows = _rowids(session, "fts_document")
    for entity_id, entity_type in existing.items():
        key = keys.get(entity_id)
        if key is None:
            collector.add("fts", f"{entity_id} has no search key")
            continue
        if key[0] not in entity_rows:
            collector.add("fts", f"{entity_id} has no fts_entity row")
        if entity_type == "document" and key[0] not in document_rows:
            collector.add("fts", f"{entity_id} has no fts_document row")
    known_rowids = {rowid for rowid, _ in keys.values()}
    for entity_id in keys:
        if entity_id not in existing:
            collector.add("fts", f"search key of missing entity {entity_id}")
    for table, rowids in (("fts_entity", entity_rows), ("fts_document", document_rows)):
        for rowid in sorted(rowids - known_rowids):
            collector.add("fts", f"orphaned {table} row {rowid}")


def _check_derived(session: Session, settings: Settings, collector: _Collector) -> None:
    ids = derived.all_entity_ids(session)
    stored = derived.stored_rows(session, ids)
    computed = derived.compute_for(session, ids, settings)
    for entity_id in ids:
        if entity_id not in stored:
            collector.add("derived", f"{entity_id} has no derived row")
        elif stored[entity_id] != computed[entity_id]:
            collector.add("derived", f"derived row of {entity_id} is out of date")


def _latest_revisions(session: Session) -> dict[str, Revision]:
    latest = (
        select(Revision.entity_id, func.max(Revision.version).label("version"))
        .group_by(Revision.entity_id)
        .subquery()
    )
    rows = session.scalars(
        select(Revision).join(
            latest,
            (Revision.entity_id == latest.c.entity_id) & (Revision.version == latest.c.version),
        )
    )
    return {revision.entity_id: revision for revision in rows}


def _check_revisions(session: Session, collector: _Collector) -> None:
    latest = _latest_revisions(session)
    for spec in ENTITY_TYPES.values():
        rows = [dict(row) for row in session.execute(select(table_of(spec))).mappings()]
        links = load_links(session, [row["id"] for row in rows]) if spec.has_field("links") else {}
        for row in rows:
            revision = latest.get(row["id"])
            if revision is None:
                collector.add("revision", f"{row['id']} has no revision")
                continue
            snapshot = revision.snapshot or {}
            if revision.version != row["version"]:
                collector.add(
                    "revision",
                    f"{row['id']} has version {row['version']} but its latest revision is "
                    f"{revision.version}",
                )
            fields = tracked_values(spec, row, links.get(row["id"]))
            changes, missing = diff_fields(spec, snapshot.get("fields") or {}, fields)
            # A field added by a later migration is not recorded in older snapshots; that
            # is fine while it is still empty (e.g. document.source_record_at, 0002).
            differing = list(changes) + [
                name for name in missing if name not in fields or not is_empty(fields[name])
            ]
            if differing:
                collector.add(
                    "revision", f"{row['id']} differs from its snapshot in {_names(differing)}"
                )
            if canonical_json(field_meta_of(spec, row)) != canonical_json(
                snapshot.get("field_meta") or {}
            ):
                collector.add("revision", f"{row['id']} field_meta differs from its snapshot")
            if canonical_json(state_of(spec, row)) != canonical_json(snapshot.get("state") or {}):
                collector.add("revision", f"{row['id']} state differs from its snapshot")


def _check_verifications(session: Session, collector: _Collector) -> None:
    """Every field marked ``verified`` rests on a live evidence row of the same record
    that targets the field and quotes the source (DATA_MODEL §5, §6.4), whatever the
    record's deletion state."""
    evidence = {
        row.id: row
        for row in session.execute(
            select(
                Evidence.id,
                Evidence.subject_id,
                Evidence.target,
                Evidence.deleted_at,
                Evidence.quote,
            )
        )
    }
    for spec in ENTITY_TYPES.values():
        if not spec.curated:
            continue
        table = table_of(spec)
        for entity_id, field_meta in session.execute(select(table.c.id, table.c.field_meta)):
            for name, entry in sorted((field_meta or {}).items()):
                if not isinstance(entry, dict) or entry.get("verified") != "verified":
                    continue
                evidence_id = entry.get("evidence_id")
                found = evidence.get(evidence_id) if isinstance(evidence_id, str) else None
                where = f"{entity_id}.{name} is verified"
                if found is None:
                    collector.add("verification", f"{where} with missing evidence {evidence_id}")
                elif found.deleted_at is not None:
                    collector.add("verification", f"{where} with deleted evidence {evidence_id}")
                elif found.subject_id != entity_id or found.target != f"field:{name}":
                    collector.add(
                        "verification",
                        f"{where} with evidence {evidence_id} of another record or field",
                    )
                elif not found.quote:
                    collector.add(
                        "verification", f"{where} with evidence {evidence_id} without a quote"
                    )


def _check_acquisition_references(
    session: Session, existing: dict[str, str], collector: _Collector
) -> None:
    """Phase 2 references (DATA_MODEL §13): raw snapshots named by documents, evidence,
    proposals, the fetch log and ``field_meta[*].raw_snapshot_ids``; document texts; the
    records named by observations and open proposals."""
    snapshots = set(session.execute(select(RawSnapshot.id)).scalars())
    for kind, rows in (
        ("document", select(Document.id, Document.raw_snapshot_id)),
        ("evidence", select(Evidence.id, Evidence.raw_snapshot_id)),
        ("proposal", select(Proposal.id, Proposal.raw_snapshot_id)),
        ("fetch_log", select(FetchLog.id, FetchLog.raw_snapshot_id)),
    ):
        for row_id, snapshot_id in session.execute(rows):
            if snapshot_id is not None and snapshot_id not in snapshots:
                collector.add(
                    "reference", f"{kind} {row_id} refers to missing raw snapshot {snapshot_id}"
                )
    for spec in ENTITY_TYPES.values():
        if not spec.curated:
            continue
        table = table_of(spec)
        for entity_id, field_meta in session.execute(select(table.c.id, table.c.field_meta)):
            for name, entry in sorted((field_meta or {}).items()):
                ids = entry.get("raw_snapshot_ids") if isinstance(entry, dict) else None
                for snapshot_id in ids or ():
                    if snapshot_id not in snapshots:
                        collector.add(
                            "reference",
                            f"{entity_id}.{name} names missing raw snapshot {snapshot_id}",
                        )
    texts = set(session.execute(select(DocumentText.text_hash)).scalars())
    for document_id, text_hash in session.execute(
        select(Document.id, Document.text_hash).where(Document.text_hash.is_not(None))
    ):
        if text_hash not in texts:
            collector.add("reference", f"{document_id} has no document text {text_hash}")
    for observation_id, subject_id in session.execute(
        select(SourceObservation.id, SourceObservation.subject_id).where(
            SourceObservation.subject_id.is_not(None)
        )
    ):
        if subject_id not in existing:
            collector.add(
                "reference", f"observation {observation_id} refers to missing {subject_id}"
            )
    for proposal_id, subject_id, related_id in session.execute(
        select(Proposal.id, Proposal.subject_id, Proposal.related_id).where(
            Proposal.state == "open"
        )
    ):
        for value in (subject_id, related_id):
            if value is not None and value not in existing:
                collector.add("reference", f"open proposal {proposal_id} refers to missing {value}")


def _check_merges(session: Session, existing: dict[str, str], collector: _Collector) -> None:
    """Merged records stay deleted and name an existing survivor (DATA_MODEL §13, §18)."""
    for spec in ENTITY_TYPES.values():
        if not spec.curated:
            continue
        table = table_of(spec)
        for entity_id, merged_into, deleted_at in session.execute(
            select(table.c.id, table.c.merged_into, table.c.deleted_at).where(
                table.c.merged_into.is_not(None)
            )
        ):
            if deleted_at is None:
                collector.add("merge", f"{entity_id} is merged into {merged_into} but not deleted")
            if merged_into not in existing:
                collector.add("merge", f"{entity_id} is merged into missing {merged_into}")


def _names(names: Iterable[str]) -> str:
    return ", ".join(sorted(names))
