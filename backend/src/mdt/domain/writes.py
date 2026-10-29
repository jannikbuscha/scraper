"""Write machinery shared by all write actions (docs/DATA_MODEL.md §6.1-§6.3).

Every function here runs inside a write unit opened by :func:`mdt.db.session.write_transaction`
(``BEGIN IMMEDIATE``). Rows are written with SQLAlchemy Core: inserts, and updates as a
compare-and-swap on ``version``. JSON values are always new objects, never modified in
place. Each successful change writes exactly one revision with a full snapshot.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mdt.config import Settings
from mdt.db.models import DocumentLink, Revision
from mdt.db.session import schema_revision, session_settings
from mdt.domain import derived, fts
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.conflicts import conflict_payload
from mdt.domain.errors import (
    ConflictError,
    EntityDeletedError,
    LockedFieldError,
    NotFoundError,
    Problems,
    UniqueViolationError,
    ValidationError,
)
from mdt.domain.fieldmeta import value_entry
from mdt.domain.ids import new_id
from mdt.domain.normalize import (
    INVALID,
    LINK_READ_ONLY_KEYS,
    ValueProblem,
    is_empty,
    normalize_note,
    normalize_value,
    values_equal,
)
from mdt.domain.records import (
    Row,
    field_meta_of,
    load_links,
    load_row,
    state_of,
    stored_values,
    table_of,
    to_columns,
)
from mdt.domain.registry import ENTITY_TYPES, EntityTypeSpec, FieldSpec
from mdt.domain.snapshots import Snapshot, diff_fields, diff_snapshots, make_snapshot
from mdt.domain.urls import canonical_url
from mdt.domain.validation import RecordCheck, WriteWarning, validate_record
from mdt.domain.vocab import TermIndex


@dataclass
class ChangeResult:
    """Outcome of a write action."""

    entity_type: str
    entity_id: str
    changed: bool
    version: int
    revision_id: int | None
    snapshot: Snapshot
    warnings: list[WriteWarning] = field(default_factory=list)
    batch_id: str | None = None

    def warnings_payload(self) -> list[dict[str, Any]]:
        """``warnings`` as in API responses."""
        return [warning.as_dict() for warning in self.warnings]


@dataclass
class WriteUnit:
    """Context of one write unit: one timestamp for every value written in it."""

    session: Session
    spec: EntityTypeSpec
    actor: Actor
    ts: str
    settings: Settings
    terms: TermIndex
    schema_revision: str | None

    @classmethod
    def open(cls, session: Session, spec: EntityTypeSpec, actor: Actor) -> WriteUnit:
        """Create the context inside an open write transaction."""
        return cls(
            session=session,
            spec=spec,
            actor=actor,
            ts=utc_now(),
            settings=session_settings(session),
            terms=TermIndex(session),
            schema_revision=schema_revision(session),
        )

    def for_type(self, spec: EntityTypeSpec) -> WriteUnit:
        """The same unit (timestamp, actor) for another entity type."""
        return WriteUnit(
            self.session, spec, self.actor, self.ts, self.settings, self.terms, self.schema_revision
        )


@dataclass(frozen=True)
class RestoreMeta:
    """Provenance of restored values (DATA_MODEL §5, channel restore)."""

    version: int
    revision_id: int
    sources: Mapping[str, str | None]


def entity_spec(entity_type: str) -> EntityTypeSpec:
    """The registry entry of ``entity_type``; unknown types are 404."""
    spec = ENTITY_TYPES.get(entity_type)
    if spec is None:
        raise NotFoundError("Unknown entity type")
    return spec


def clean_note(note: Any) -> str | None:
    """Normalise a revision note (≤ 2 000 characters)."""
    try:
        return normalize_note(note)
    except ValueProblem as exc:
        raise ValidationError.single("note", str(exc)) from exc


def require_row(unit: WriteUnit, entity_id: str) -> Row:
    """Read the row inside the write unit; 404 if missing."""
    row = load_row(unit.session, unit.spec, entity_id)
    if row is None:
        raise NotFoundError()
    return row


def links_of(unit: WriteUnit, row: Row) -> list[dict[str, Any]] | None:
    """Current document links (None for other types)."""
    if not unit.spec.has_field("links"):
        return None
    return load_links(unit.session, [row["id"]])[row["id"]]


def snapshot_of(spec: EntityTypeSpec, row: Row, links: list[dict[str, Any]] | None) -> Snapshot:
    """The snapshot of a stored row."""
    values = stored_values(spec, row, links)
    return make_snapshot(
        {f.name: values[f.name] for f in spec.tracked_fields},
        field_meta_of(spec, row),
        state_of(spec, row),
    )


def ensure_live(row: Row) -> None:
    """Writes to a deleted row are refused (409 entity_deleted)."""
    if row["deleted_at"] is not None:
        raise EntityDeletedError(row["deleted_at"], row["deleted_by"])


def check_version(
    unit: WriteUnit,
    row: Row,
    expected_version: int | None,
    *,
    action: str,
    your_changes: Mapping[str, Any],
) -> None:
    """Optimistic locking: ``expected_version`` is required from clients; a mismatch
    raises :class:`ConflictError` with the full payload."""
    if expected_version is None:
        if unit.actor.is_client:
            raise ValidationError.single("expected_version", "is required")
        return
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ValidationError.single("expected_version", "must be an integer")
    if expected_version != row["version"]:
        raise ConflictError(
            conflict_payload(
                unit.session,
                unit.spec,
                row,
                links_of(unit, row),
                action=action,
                base_version=expected_version,
                your_changes=your_changes,
            )
        )


def _write_refusal(spec: FieldSpec, actor: Actor, creating: bool, allow_system: bool) -> str | None:
    if spec.derived:
        return "is derived and cannot be set"
    if spec.virtual or spec.system_column or spec.computed_from:
        return "is computed and cannot be set"
    if spec.internal:
        return None if creating and actor.channel == "seed" else "cannot be set"
    if spec.create_only and not creating:
        return "can only be set when the record is created"
    if spec.system:
        return None if allow_system or not actor.is_client else "is set by the system"
    if not spec.editable:
        return "cannot be set"
    return None


def normalize_changes(
    unit: WriteUnit, changes: Any, *, creating: bool, allow_system: bool = False
) -> dict[str, Any]:
    """Check that every key is a writable field on this channel and normalise the values."""
    if not isinstance(changes, Mapping):
        raise ValidationError.single("changes", "must be an object")
    problems = Problems()
    normalized: dict[str, Any] = {}
    for name, value in changes.items():
        if not isinstance(name, str) or not unit.spec.has_field(name):
            problems.add(str(name), "is not a field of this entity type")
            continue
        field_spec = unit.spec.field(name)
        refusal = _write_refusal(field_spec, unit.actor, creating, allow_system)
        if refusal:
            problems.add(name, refusal)
            continue
        result = normalize_value(field_spec, value, problems)
        if result is not INVALID:
            normalized[name] = result
    problems.raise_if_any()
    return normalized


def complete_links(
    links: list[dict[str, Any]], current: list[dict[str, Any]] | None, actor: Actor
) -> list[dict[str, Any]]:
    """Fill the origin and the read-only keys of document links.

    The origin is provenance. On channel ui a stored link keeps its origin, a new link
    gets ``manual``, and the read-only keys of the input are ignored. Collectors create
    ``auto`` links. A restore brings back the links of a stored snapshot as recorded
    (origin and match details). The other machine channels may state the origin of new
    links.
    """
    stored = {link["subject_id"]: link for link in current or []}
    result = []
    for link in links:
        existing = stored.get(link["subject_id"])
        if actor.channel == "restore":
            origin = link.get("origin") or (existing["origin"] if existing else "manual")
        elif existing is not None:
            origin = existing["origin"]
        elif actor.channel == "ui":
            origin = "manual"
        elif actor.channel == "collector":
            origin = "auto"
        else:
            origin = link.get("origin") or "manual"
        item = {
            "subject_id": link["subject_id"],
            "origin": origin,
            "state": link["state"],
            "matched_aliases": list(existing["matched_aliases"]) if existing else [],
            "match_count": existing["match_count"] if existing else 0,
            "snippet": existing["snippet"] if existing else None,
        }
        if actor.channel != "ui":
            for key in LINK_READ_ONLY_KEYS:
                if key in link:
                    item[key] = copy.deepcopy(link[key])
        result.append(item)
    return sorted(result, key=lambda item: item["subject_id"])


def sync_links(session: Session, document_id: str, links: list[dict[str, Any]]) -> None:
    """Make ``document_link`` rows match ``links`` (part of the document's snapshot)."""
    table = cast(Table, DocumentLink.__table__)
    existing = {
        row.subject_id: row
        for row in session.execute(select(table).where(table.c.document_id == document_id))
    }
    wanted = {link["subject_id"]: link for link in links}
    removed = [subject for subject in existing if subject not in wanted]
    if removed:
        session.execute(
            delete(table).where(table.c.document_id == document_id, table.c.subject_id.in_(removed))
        )
    for subject_id, link in wanted.items():
        values = {
            "origin": link["origin"],
            "state": link["state"],
            "matched_aliases": list(link["matched_aliases"]),
            "match_count": link["match_count"],
            "snippet": link["snippet"],
        }
        if subject_id in existing:
            session.execute(
                update(table)
                .where(table.c.document_id == document_id, table.c.subject_id == subject_id)
                .values(**values)
            )
        else:
            session.execute(
                insert(table).values(document_id=document_id, subject_id=subject_id, **values)
            )


def _computed_values(spec: EntityTypeSpec, values: dict[str, Any]) -> dict[str, Any]:
    """Dependent system fields recomputed from their source field (canonical_url)."""
    result: dict[str, Any] = {}
    if spec.has_field("canonical_url"):
        url = values.get("url")
        result["canonical_url"] = canonical_url(url) if url else None
    return result


def insert_revision(
    unit: WriteUnit,
    *,
    entity_id: str,
    version: int,
    action: str,
    note: str | None,
    snapshot: Snapshot,
    diff: Mapping[str, Any],
    batch_id: str | None,
    conflict_action: str,
    restored_from: int | None = None,
    restored_from_version: int | None = None,
) -> int:
    """Append the revision; a duplicate ``(entity_id, version)`` is a 409 conflict
    (reported with ``conflict_action``)."""
    values = {
        "entity_type": unit.spec.name,
        "entity_id": entity_id,
        "version": version,
        "at": unit.ts,
        "author": unit.actor.by,
        "channel": unit.actor.channel,
        "action": action,
        "note": note,
        "run_id": unit.actor.run_id,
        "proposal_id": None,
        "restored_from": restored_from,
        "restored_from_version": restored_from_version,
        "batch_id": batch_id,
        "schema_revision": unit.schema_revision,
        "snapshot": snapshot,
        "diff": dict(diff),
    }
    try:
        result = unit.session.execute(insert(Revision).values(**values).returning(Revision.id))
    except IntegrityError as exc:
        if "revision" not in str(exc.orig):
            raise
        row = require_row(unit, entity_id)
        raise ConflictError(
            conflict_payload(
                unit.session,
                unit.spec,
                row,
                links_of(unit, row),
                action=conflict_action,
                base_version=version - 1,
                your_changes={},
            )
        ) from exc
    return int(result.scalar_one())


def cas_update(unit: WriteUnit, row: Row, values: Mapping[str, Any], *, action: str) -> int:
    """``UPDATE … SET …, version = version + 1 WHERE id = :id AND version = :v``.

    Returns the new version; zero affected rows raise :class:`ConflictError`.
    """
    table = table_of(unit.spec)
    try:
        result = unit.session.execute(
            update(table)
            .where(table.c.id == row["id"], table.c.version == row["version"])
            .values(**values, version=table.c.version + 1)
        )
    except IntegrityError as exc:
        mapped = unique_from_integrity(exc)
        if mapped is None:
            raise
        raise mapped from exc
    if result.rowcount != 1:  # type: ignore[attr-defined]
        fresh = require_row(unit, row["id"])
        raise ConflictError(
            conflict_payload(
                unit.session,
                unit.spec,
                fresh,
                links_of(unit, fresh),
                action=action,
                base_version=int(row["version"]),
                your_changes={},
            )
        )
    return int(row["version"]) + 1


def unique_from_integrity(exc: IntegrityError) -> UniqueViolationError | None:
    """Map a UNIQUE constraint failure on an entity table to ``unique_violation`` (the
    explicit checks normally catch these first)."""
    message = str(exc.orig)
    prefix = "UNIQUE constraint failed: "
    if prefix not in message:
        return None
    column = message.split(prefix, 1)[1].split(",")[0].strip().split(".")[-1]
    return UniqueViolationError(column, None)


def apply_effects(
    unit: WriteUnit, entity_id: str, old: Mapping[str, Any] | None, new: Mapping[str, Any]
) -> None:
    """Refresh the FTS rows and recompute derived values where DATA_MODEL §8.1 requires."""
    session, spec = unit.session, unit.spec
    fts.index_entity(session, spec, entity_id, new)
    if spec.name == "event":
        subjects = {new.get("subject_id"), (old or {}).get("subject_id")}
        derived.recompute(session, [s for s in subjects if s], unit.ts, unit.settings)
    elif spec.name == "participation":
        focal = derived.focal_org_id(session, unit.settings)
        organizations = {new.get("organization_id"), (old or {}).get("organization_id")}
        if focal is not None and focal in organizations:
            subjects = {new.get("subject_id"), (old or {}).get("subject_id")}
            derived.recompute(session, [s for s in subjects if s], unit.ts, unit.settings)
    elif spec.name == "vocabulary_term" and new.get("vocabulary") == "event_type":
        derived.recompute_all(session, unit.ts, unit.settings)


def create_record(
    unit: WriteUnit,
    provided: dict[str, Any],
    *,
    note: str | None,
    batch_id: str | None,
    extra_values: Mapping[str, Any] | None = None,
) -> ChangeResult:
    """Create a record from normalised ``provided`` values (DATA_MODEL §6.2 step 2).

    ``extra_values`` are values set by the domain layer (defaults computed by the caller,
    e.g. a comment's status); they count as assigned but get no provenance entry.
    """
    spec, session, actor = unit.spec, unit.session, unit.actor
    entity_id = new_id(spec.prefix)
    new: dict[str, Any] = {
        f.name: copy.deepcopy(f.default) if f.default is not None else f.empty_value()
        for f in spec.stored_fields
    }
    new.update(provided)
    new.update(extra_values or {})
    if "links" in provided:
        new["links"] = complete_links(provided["links"], None, actor)
    computed = _computed_values(spec, new)
    new.update(computed)
    assigned = frozenset(provided) | frozenset(extra_values or {}) | frozenset(computed)
    check = RecordCheck(
        session=session,
        spec=spec,
        actor=actor,
        terms=unit.terms,
        entity_id=entity_id,
        current=None,
        new=new,
        assigned=assigned,
        provided=provided,
        note=note,
    )
    validate_record(check)

    meta: dict[str, Any] = {}
    if spec.curated:
        for name, value in provided.items():
            if spec.field(name).tracked and not is_empty(value):
                meta[name] = value_entry(actor, unit.ts)
        if "canonical_url" in computed and new.get("canonical_url") and "url" in meta:
            meta["canonical_url"] = copy.deepcopy(meta["url"])
        for name in extra_values or {}:
            if spec.field(name).tracked and not is_empty(new[name]) and name not in meta:
                meta[name] = value_entry(actor, unit.ts)

    row: dict[str, Any] = {
        "id": entity_id,
        "version": 1,
        "created_at": unit.ts,
        "created_by": actor.by,
        "updated_at": unit.ts,
        "updated_by": actor.by,
    }
    for field_spec in spec.stored_fields:
        row.update(to_columns(field_spec, new[field_spec.name]))
    if spec.curated:
        row["field_meta"] = meta
    try:
        session.execute(insert(table_of(spec)).values(**row))
    except IntegrityError as exc:
        mapped = unique_from_integrity(exc)
        if mapped is None:
            raise
        raise mapped from exc
    if spec.has_field("links") and new.get("links"):
        sync_links(session, entity_id, new["links"])
    if spec.has_derived:
        derived.recompute(session, [entity_id], unit.ts, unit.settings)

    state = {"deleted_at": None, "deleted_by": None}
    if spec.curated:
        state["merged_into"] = None
    snapshot = make_snapshot({f.name: new[f.name] for f in spec.tracked_fields}, meta, state)
    fields_diff, _ = diff_fields(spec, None, snapshot["fields"])
    revision_id = insert_revision(
        unit,
        entity_id=entity_id,
        version=1,
        action="create",
        note=note,
        snapshot=snapshot,
        diff={"fields": fields_diff} if fields_diff else {},
        batch_id=batch_id,
        conflict_action="comment" if spec.name == "comment" else "patch",
    )
    apply_effects(unit, entity_id, None, new)
    return ChangeResult(
        entity_type=spec.name,
        entity_id=entity_id,
        changed=True,
        version=1,
        revision_id=revision_id,
        snapshot=snapshot,
        warnings=check.warnings,
        batch_id=batch_id,
    )


def update_record(
    unit: WriteUnit,
    row: Row,
    provided: dict[str, Any],
    *,
    note: str | None,
    expected_version: int | None,
    batch_id: str | None,
    action: str = "update",
    conflict_action: str = "patch",
    restore: RestoreMeta | None = None,
) -> ChangeResult:
    """Apply normalised changes to a live row (DATA_MODEL §6.2 step 3).

    No differing value → no-op (no revision, no version bump, ``changed = False``).
    """
    spec, session, actor = unit.spec, unit.session, unit.actor
    entity_id = row["id"]
    ensure_live(row)
    check_version(unit, row, expected_version, action=conflict_action, your_changes=provided)
    links = links_of(unit, row)
    current = stored_values(spec, row, links)
    new = dict(current)
    new.update(provided)
    if "links" in provided:
        new["links"] = complete_links(provided["links"], current.get("links"), actor)
    changed = {
        name for name in provided if not values_equal(spec.field(name), current[name], new[name])
    }
    for name, value in _computed_values(spec, new).items():
        new[name] = value
        if not values_equal(spec.field(name), current[name], value):
            changed.add(name)
    old_meta = field_meta_of(spec, row)
    if not changed:
        return ChangeResult(
            entity_type=spec.name,
            entity_id=entity_id,
            changed=False,
            version=int(row["version"]),
            revision_id=None,
            snapshot=snapshot_of(spec, row, links),
        )
    if actor.channel == "collector":
        locked = [
            name
            for name in changed
            if not spec.field(name).computed_from and (old_meta.get(name) or {}).get("locked")
        ]
        if locked:
            raise LockedFieldError(locked)
    check = RecordCheck(
        session=session,
        spec=spec,
        actor=actor,
        terms=unit.terms,
        entity_id=entity_id,
        current=current,
        new=new,
        assigned=frozenset(changed),
        provided=provided,
        note=note,
    )
    validate_record(check)

    meta = copy.deepcopy(old_meta)
    if spec.curated:
        for name in changed:
            field_spec = spec.field(name)
            if not field_spec.tracked or field_spec.computed_from:
                continue
            if restore is not None:
                meta[name] = value_entry(
                    actor,
                    unit.ts,
                    restored_src=restore.sources.get(name),
                    restored_from_version=restore.version,
                )
            else:
                meta[name] = value_entry(actor, unit.ts)
        if "canonical_url" in changed and "url" in meta:
            meta["canonical_url"] = copy.deepcopy(meta["url"])

    values: dict[str, Any] = {"updated_at": unit.ts, "updated_by": actor.by}
    for name in changed:
        values.update(to_columns(spec.field(name), new[name]))
    if spec.curated:
        values["field_meta"] = meta
    version = cas_update(unit, row, values, action=conflict_action)
    if "links" in changed:
        sync_links(session, entity_id, new["links"])

    old_snapshot = make_snapshot(
        {f.name: current[f.name] for f in spec.tracked_fields}, old_meta, state_of(spec, row)
    )
    snapshot = make_snapshot(
        {f.name: new[f.name] for f in spec.tracked_fields}, meta, state_of(spec, row)
    )
    diff, _ = diff_snapshots(spec, old_snapshot, snapshot)
    revision_id = insert_revision(
        unit,
        entity_id=entity_id,
        version=version,
        action=action,
        note=note,
        snapshot=snapshot,
        diff=diff,
        batch_id=batch_id,
        conflict_action=conflict_action,
        restored_from=restore.revision_id if restore else None,
        restored_from_version=restore.version if restore else None,
    )
    apply_effects(unit, entity_id, current, new)
    return ChangeResult(
        entity_type=spec.name,
        entity_id=entity_id,
        changed=True,
        version=version,
        revision_id=revision_id,
        snapshot=snapshot,
        warnings=check.warnings,
        batch_id=batch_id,
    )


def write_state_change(
    unit: WriteUnit,
    row: Row,
    *,
    action: str,
    note: str | None,
    batch_id: str | None,
    deleted: bool,
) -> ChangeResult:
    """Soft delete or undelete one row: state change, version bump, revision."""
    spec = unit.spec
    links = links_of(unit, row)
    before = snapshot_of(spec, row, links)
    values: dict[str, Any] = {
        "deleted_at": unit.ts if deleted else None,
        "deleted_by": unit.actor.by if deleted else None,
        "updated_at": unit.ts,
        "updated_by": unit.actor.by,
    }
    version = cas_update(unit, row, values, action=action)
    after_row = {**row, **values, "version": version}
    snapshot = snapshot_of(spec, after_row, links)
    diff, _ = diff_snapshots(spec, before, snapshot)
    revision_id = insert_revision(
        unit,
        entity_id=row["id"],
        version=version,
        action=action,
        note=note,
        snapshot=snapshot,
        diff=diff,
        batch_id=batch_id,
        conflict_action=action,
    )
    current = stored_values(spec, after_row, links)
    apply_effects(unit, row["id"], current, current)
    return ChangeResult(
        entity_type=spec.name,
        entity_id=row["id"],
        changed=True,
        version=version,
        revision_id=revision_id,
        snapshot=snapshot,
        batch_id=batch_id,
    )
