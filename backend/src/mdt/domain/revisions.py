"""Public write actions (docs/DATA_MODEL.md §6.2, §6.4).

Every function is one write unit (``BEGIN IMMEDIATE``; bulk: one unit per item) and
takes a Session, the entity type, IDs, payloads in API representation and an
:class:`~mdt.domain.actor.Actor`. The HTTP layer calls them directly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import Evidence, Revision, Service
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import (
    DomainError,
    EvidenceRequiredError,
    HasDependentsError,
    InvalidStateError,
    NotDeletableError,
    NotFoundError,
    Problems,
    ReferenceDeletedError,
    ValidationError,
)
from mdt.domain.fieldmeta import entry_diff, verification_entry
from mdt.domain.history import get_revision, latest_revision
from mdt.domain.ids import new_batch_id
from mdt.domain.labels import ref_info
from mdt.domain.normalize import INVALID, is_empty, normalize_value, values_equal
from mdt.domain.records import (
    Row,
    api_value,
    field_meta_of,
    load_links,
    load_row,
    state_of,
    stored_values,
)
from mdt.domain.registry import ENTITY_TYPES, EntityTypeSpec, type_of_id
from mdt.domain.snapshots import make_snapshot
from mdt.domain.validation import (
    DELETED_REFS_ALLOWED,
    EVIDENCE_QUOTE_MESSAGE,
    check_unique,
    ref_row,
    verification_rests_on,
)
from mdt.domain.writes import (
    ChangeResult,
    RestoreMeta,
    WriteUnit,
    apply_effects,
    clean_note,
    create_record,
    ensure_live,
    entity_spec,
    insert_revision,
    links_of,
    normalize_changes,
    require_row,
    snapshot_of,
    update_record,
    update_row,
    write_state_change,
)

VERIFICATION_STATUSES = ("unverified", "verified", "disputed")
MAX_BULK_ITEMS = 500


@dataclass
class RestoreResult(ChangeResult):
    """Outcome of a restore (or its dry run)."""

    changes: dict[str, list[Any]] = field(default_factory=dict)
    skipped_fields: list[str] = field(default_factory=list)
    dry_run: bool = False


@dataclass
class BulkItemResult:
    """Per-item result of a bulk edit (API §3.2): ``updated``, ``unchanged`` or
    ``entity_deleted`` (each with the record's ``version``) or ``error``."""

    id: str
    status: str
    version: int | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """The API representation."""
        return {"id": self.id, "status": self.status, "version": self.version, "error": self.error}


@dataclass
class BulkResult:
    """Outcome of a bulk edit."""

    batch_id: str
    results: list[BulkItemResult]


# --------------------------------------------------------------------------------------
# apply_change
# --------------------------------------------------------------------------------------


def apply_change(
    session: Session,
    entity_type: str,
    entity_id: str | None,
    changes: Mapping[str, Any],
    actor: Actor,
    *,
    note: str | None = None,
    batch_id: str | None = None,
) -> ChangeResult:
    """Create (``entity_id=None``) or update a record through the one write path.

    Comments are delegated to :mod:`mdt.domain.comments`, which adds their rules.
    """
    if entity_type == "comment":
        from mdt.domain import comments

        if entity_id is None:
            return comments.create_comment_from_changes(session, changes, actor, note=note)
        return comments.edit_comment_from_changes(session, entity_id, changes, actor, note=note)
    spec = entity_spec(entity_type)
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, spec, actor)
        if entity_id is None:
            provided = normalize_changes(unit, changes, creating=True)
            provided, extra = _create_defaults(unit, provided)
            return create_record(unit, provided, note=clean, batch_id=batch_id, extra_values=extra)
        row = require_row(unit, entity_id)
        ensure_live(row)
        provided = normalize_changes(unit, changes, creating=False)
        return update_record(unit, row, provided, note=clean, batch_id=batch_id)


def _create_defaults(
    unit: WriteUnit, provided: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Type-specific defaults on create: evidence ``retrieved_at`` (now, on channel ui)
    and ``value_snapshot`` (the target field's current value), DATA_MODEL §3.5."""
    if unit.spec.name != "evidence":
        return provided, {}
    if unit.actor.channel == "ui" and provided.get("retrieved_at") is None:
        provided = {**provided, "retrieved_at": unit.ts}
    return provided, {"value_snapshot": _target_value(unit.session, provided)}


def _target_value(session: Session, provided: Mapping[str, Any]) -> Any:
    target, subject_id = provided.get("target"), provided.get("subject_id")
    if not isinstance(target, str) or not target.startswith("field:") or not subject_id:
        return None
    subject_type = type_of_id(subject_id)
    if subject_type is None:
        return None
    spec = ENTITY_TYPES[subject_type]
    name = target.removeprefix("field:")
    if not spec.has_field(name) or not spec.field(name).stored:
        return None
    row = load_row(session, spec, subject_id)
    if row is None:
        return None
    links = load_links(session, [subject_id])[subject_id] if name == "links" else None
    return api_value(spec.field(name), row, links)


# --------------------------------------------------------------------------------------
# Field verification
# --------------------------------------------------------------------------------------


def set_field_verification(
    session: Session,
    entity_type: str,
    entity_id: str,
    field_name: str,
    status: str,
    actor: Actor,
    *,
    note: str | None = None,
    evidence_id: str | None = None,
) -> ChangeResult:
    """Set a field's verification status (DATA_MODEL §6.4); the revision has a meta diff
    only. Setting the status that is already set (same evidence) is a no-op."""
    spec = entity_spec(entity_type)
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, spec, actor)
        row = require_row(unit, entity_id)
        ensure_live(row)
        links = links_of(unit, row)
        values = stored_values(spec, row, links)
        _check_verifiable(spec, values, field_name, status, clean)
        if status == "verified":
            _require_evidence(session, entity_id, field_name, evidence_id)
        meta = field_meta_of(spec, row)
        old_entry = meta.get(field_name)
        new_entry = verification_entry(old_entry, actor, unit.ts, status, evidence_id)
        changes = entry_diff(old_entry, new_entry)
        if old_entry is not None and not changes:
            return ChangeResult(
                spec.name,
                entity_id,
                False,
                int(row["version"]),
                None,
                snapshot_of(spec, row, links),
            )
        meta[field_name] = new_entry
        update = {"field_meta": meta, "updated_at": unit.ts, "updated_by": actor.by}
        version = update_row(unit, row, update)
        snapshot = make_snapshot(
            {f.name: values[f.name] for f in spec.tracked_fields}, meta, state_of(spec, row)
        )
        revision_id = insert_revision(
            unit,
            entity_id=entity_id,
            version=version,
            action="verify",
            note=clean,
            snapshot=snapshot,
            diff={"meta": {field_name: changes}},
            batch_id=None,
        )
        apply_effects(unit, entity_id, values, values)
        return ChangeResult(spec.name, entity_id, True, version, revision_id, snapshot)


def _check_verifiable(
    spec: EntityTypeSpec, values: Mapping[str, Any], name: str, status: str, note: str | None
) -> None:
    problems = Problems()
    if not spec.curated:
        problems.add("field", "Fields of this entity type cannot be verified")
    elif not spec.has_field(name):
        problems.add("field", "is not a field of this entity type")
    else:
        target = spec.field(name)
        if not target.tracked or target.system or name == "verification_status":
            problems.add("field", "This field cannot be verified")
        elif is_empty(values.get(name)):
            problems.add("field", "An empty field cannot be verified")
    if status not in VERIFICATION_STATUSES:
        problems.add("status", f"must be one of {', '.join(VERIFICATION_STATUSES)}")
    if status == "disputed" and not note:
        problems.add("note", "A note is required when a field is disputed")
    problems.raise_if_any()


def _require_evidence(session: Session, entity_id: str, name: str, evidence_id: str | None) -> None:
    """``verified`` needs a live evidence row of this record that targets the field and
    quotes the source verbatim (CODEBOOK §2.3, DATA_MODEL §6.4)."""
    if not evidence_id:
        raise EvidenceRequiredError()
    quote = session.execute(
        select(Evidence.quote).where(
            Evidence.id == evidence_id,
            Evidence.subject_id == entity_id,
            Evidence.target == f"field:{name}",
            Evidence.deleted_at.is_(None),
        )
    ).one_or_none()
    if quote is None:
        raise EvidenceRequiredError()
    if not quote[0]:
        raise EvidenceRequiredError(EVIDENCE_QUOTE_MESSAGE)


# --------------------------------------------------------------------------------------
# Soft delete and undelete
# --------------------------------------------------------------------------------------


def _live_dependents(session: Session, spec: EntityTypeSpec, entity_id: str) -> list[Row]:
    """Non-deleted services of a project, or the live descendants of a service."""
    service_spec = ENTITY_TYPES["service"]
    if spec.name == "project":
        ids = (
            session.execute(
                select(Service.id)
                .where(Service.project_id == entity_id, Service.deleted_at.is_(None))
                .order_by(Service.id)
            )
            .scalars()
            .all()
        )
    elif spec.name == "service":
        ids, frontier = [], [entity_id]
        while frontier:
            children = (
                session.execute(
                    select(Service.id)
                    .where(Service.parent_service_id.in_(frontier), Service.deleted_at.is_(None))
                    .order_by(Service.id)
                )
                .scalars()
                .all()
            )
            frontier = [child for child in children if child not in ids and child != entity_id]
            ids.extend(frontier)
    else:
        return []
    return [row for row in (load_row(session, service_spec, i) for i in ids) if row is not None]


def soft_delete(
    session: Session,
    entity_type: str,
    entity_id: str,
    actor: Actor,
    *,
    note: str | None = None,
    cascade: bool = False,
) -> ChangeResult:
    """Soft-delete a record (and with ``cascade`` its dependent services, in the same
    transaction and batch). Events, comments and evidence are never deleted with it.

    Evidence that a field verification rests on cannot be deleted, not even with
    ``cascade``: the field would claim a verification whose evidence is in the trash.
    The verification has to be withdrawn (or moved to other evidence) first."""
    spec = entity_spec(entity_type)
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, spec, actor)
        row = require_row(unit, entity_id)
        if not spec.deletable:
            raise NotDeletableError()
        if row["deleted_at"] is not None:
            raise InvalidStateError("deleted", "The record is already deleted")
        if spec.name == "evidence" and verification_rests_on(session, row):
            raise HasDependentsError(
                {"field_verification": 1},
                "A field is verified with this evidence. Withdraw the verification (or "
                "verify the field with other evidence) before deleting the evidence.",
            )
        dependents = _live_dependents(session, spec, entity_id)
        if dependents and not cascade:
            raise HasDependentsError({"service": len(dependents)})
        batch_id = new_batch_id()
        result = write_state_change(
            unit, row, action="delete", note=clean, batch_id=batch_id, deleted=True
        )
        service_unit = unit.for_type(ENTITY_TYPES["service"])
        for dependent in dependents:
            write_state_change(
                service_unit,
                dependent,
                action="delete",
                note=clean,
                batch_id=batch_id,
                deleted=True,
            )
        return result


def _batch_targets(
    session: Session, spec: EntityTypeSpec, row: Row
) -> list[tuple[EntityTypeSpec, Row]]:
    """Rows whose latest revision is the delete revision of this row's batch, in the
    order they were deleted (parents first)."""
    latest = latest_revision(session, row["id"])
    if latest is None or latest.action != "delete" or not latest.batch_id:
        return [(spec, row)]
    revisions = session.scalars(
        select(Revision)
        .where(Revision.batch_id == latest.batch_id, Revision.action == "delete")
        .order_by(Revision.id)
    )
    targets = []
    for revision in revisions:
        target_spec = ENTITY_TYPES[revision.entity_type]
        target = load_row(session, target_spec, revision.entity_id)
        if target is None or target["deleted_at"] is None or target["version"] != revision.version:
            continue
        targets.append((target_spec, target))
    return targets


def _check_undelete(unit: WriteUnit, row: Row) -> None:
    spec = unit.spec
    values = stored_values(spec, row, links_of(unit, row))
    check_unique(unit.session, spec, row["id"], values)
    for field_spec in spec.stored_fields:
        value = values.get(field_spec.name)
        if field_spec.type != "ref" or not field_spec.required or not value:
            continue
        if (spec.name, field_spec.name) in DELETED_REFS_ALLOWED:
            continue
        found = ref_row(unit.session, value)
        if found is not None and found[1]["deleted_at"] is not None:
            info = ref_info(unit.session, value)
            raise ReferenceDeletedError(
                field_spec.name, value, found[0], info.label if info else None
            )


def undelete(
    session: Session,
    entity_type: str,
    entity_id: str,
    actor: Actor,
    *,
    note: str | None = None,
    cascade: bool = False,
) -> ChangeResult:
    """Undelete a record; with ``cascade`` also the rows deleted in the same batch."""
    spec = entity_spec(entity_type)
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, spec, actor)
        row = require_row(unit, entity_id)
        if row["deleted_at"] is None:
            raise InvalidStateError("live", "The record is not deleted")
        targets = _batch_targets(session, spec, row) if cascade else [(spec, row)]
        if all(target["id"] != entity_id for _, target in targets):
            targets.insert(0, (spec, row))
        batch_id = new_batch_id()
        result: ChangeResult | None = None
        for target_spec, target in targets:
            target_unit = unit.for_type(target_spec)
            _check_undelete(target_unit, target)
            outcome = write_state_change(
                target_unit, target, action="undelete", note=clean, batch_id=batch_id, deleted=False
            )
            if target["id"] == entity_id:
                result = outcome
        assert result is not None
        return result


# --------------------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------------------


def restore_version(
    session: Session,
    entity_type: str,
    entity_id: str,
    version: int,
    actor: Actor,
    *,
    note: str | None = None,
    fields: Sequence[str] | None = None,
    dry_run: bool = False,
) -> RestoreResult:
    """Restore the tracked, editable, non-create-only fields of an old version whose
    value differs (optionally only ``fields``); all or nothing. ``dry_run`` only computes
    ``changes``. Runs on channel ``restore``; inactive codes are accepted with warnings."""
    spec = entity_spec(entity_type)
    clean = clean_note(note)
    restorer = actor.as_restore() if actor.channel == "ui" else actor
    if restorer.channel != "restore":
        raise ValidationError.single("channel", "Restores are made by the user (channel restore)")
    if fields is not None and (
        isinstance(fields, str) or not all(isinstance(name, str) for name in fields)
    ):
        raise ValidationError.single("fields", "must be a list of field names")
    transaction = read_transaction(session) if dry_run else write_transaction(session)
    with transaction:
        unit = WriteUnit.open(session, spec, restorer)
        row = require_row(unit, entity_id)
        ensure_live(row)
        revision = get_revision(session, entity_id, version) if isinstance(version, int) else None
        if revision is None:
            raise NotFoundError("Version not found")
        links = links_of(unit, row)
        current = stored_values(spec, row, links)
        provided, changes, skipped = _restore_plan(spec, revision.snapshot, current, fields)
        if dry_run or not changes:
            return RestoreResult(
                spec.name,
                entity_id,
                False,
                int(row["version"]),
                None,
                snapshot_of(spec, row, links),
                changes=changes,
                skipped_fields=skipped,
                dry_run=dry_run,
            )
        sources = {
            name: ((revision.snapshot.get("field_meta") or {}).get(name) or {}).get("src")
            for name in provided
        }
        result = update_record(
            unit,
            row,
            provided,
            note=clean,
            batch_id=None,
            action="restore",
            restore=RestoreMeta(version=version, revision_id=revision.id, sources=sources),
        )
        return RestoreResult(
            result.entity_type,
            result.entity_id,
            result.changed,
            result.version,
            result.revision_id,
            result.snapshot,
            warnings=result.warnings,
            changes=changes,
            skipped_fields=skipped,
        )


def _restore_plan(
    spec: EntityTypeSpec,
    snapshot: Mapping[str, Any],
    current: Mapping[str, Any],
    fields: Sequence[str] | None,
) -> tuple[dict[str, Any], dict[str, list[Any]], list[str]]:
    """(values to apply, ``{field: [current, restored]}``, skipped fields)."""
    recorded: Mapping[str, Any] = snapshot.get("fields") or {}
    requested = set(fields) if fields is not None else None
    problems = Problems()
    if requested is not None and requested - set(spec.field_map):
        problems.add("fields", "contains a name that is not a field of this entity type")
    provided: dict[str, Any] = {}
    changes: dict[str, list[Any]] = {}
    # Requested fields that are not part of snapshots (derived, virtual, system columns).
    skipped: list[str] = sorted(
        name for name in requested or () if spec.has_field(name) and not spec.field(name).tracked
    )
    for field_spec in spec.tracked_fields:
        name = field_spec.name
        if requested is not None and name not in requested:
            continue
        if name not in recorded:
            if requested is not None:
                skipped.append(name)
            continue
        differs = not values_equal(field_spec, current.get(name), recorded[name])
        if not field_spec.restorable:
            if differs or requested is not None:
                skipped.append(name)
            continue
        if not differs:
            continue
        value = normalize_value(field_spec, recorded[name], problems)
        if value is INVALID:
            continue
        provided[name] = value
        changes[name] = [current.get(name), value]
    problems.raise_if_any()
    if "in_paper_scope" in provided and "scope_note" not in provided:
        restored_note = recorded.get("scope_note", current.get("scope_note"))
        if not values_equal(spec.field("scope_note"), restored_note, current.get("scope_note")):
            raise ValidationError.single(
                "fields", "scope_note must be restored together with in_paper_scope"
            )
        provided["scope_note"] = current.get("scope_note")
    return provided, changes, skipped


# --------------------------------------------------------------------------------------
# Bulk edit
# --------------------------------------------------------------------------------------


def _check_bulk_ids(ids: Sequence[str], problems: Problems) -> None:
    if not ids:
        problems.add("ids", "must be a non-empty list")
    elif len(ids) > MAX_BULK_ITEMS:
        problems.add("ids", f"must have at most {MAX_BULK_ITEMS} items")
    seen: set[str] = set()
    for index, entity_id in enumerate(ids):
        if not entity_id:
            problems.add(f"ids[{index}]", "is required")
        elif entity_id in seen:
            problems.add(f"ids[{index}]", "is duplicated")
        seen.add(entity_id)


def _parse_bulk_operations(
    spec: EntityTypeSpec,
    operations: Mapping[str, Any],
    note: str | None,
    problems: Problems,
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {"set": {}, "add": {}, "remove": {}}
    owners: dict[str, list[str]] = {}
    for op_name, op in operations.items():
        if not isinstance(op, Mapping):
            problems.add(op_name, "must be an object")
            continue
        for name, value in op.items():
            path = f"{op_name}.{name}"
            owners.setdefault(name, []).append(op_name)
            if not spec.has_field(name):
                problems.add(path, "is not a field of this entity type")
                continue
            target = spec.field(name)
            scope_note = name == "scope_note" and op_name == "set" and "in_paper_scope" in op
            if not target.bulk_editable and not scope_note:
                problems.add(path, "cannot be bulk-edited")
                continue
            if op_name in ("add", "remove") and not target.is_list:
                problems.add(path, "add and remove need a list field")
                continue
            result = normalize_value(target, value, problems, path)
            if result is not INVALID:
                normalized[op_name][name] = result
    for name, ops in owners.items():
        if len(ops) > 1:
            problems.add(name, "may appear in only one of set, add and remove")
    set_values = normalized["set"]
    if "in_paper_scope" in set_values and is_empty(set_values.get("scope_note")):
        problems.add("set.scope_note", "A scope note is required when the scope is changed")
    if set_values.get("screening_status") == "excluded" and is_empty(
        set_values.get("screening_reason")
    ):
        problems.add("set.screening_reason", "An exclusion reason is required in the same set")
    if set_values.get("verification_status") in ("verified", "disputed") and not note:
        problems.add(
            "note", "A note is required when the verification status is verified or disputed"
        )
    return normalized


def bulk_apply(
    session: Session,
    entity_type: str,
    ids: Sequence[str],
    actor: Actor,
    *,
    set_values: Mapping[str, Any] | None = None,
    add: Mapping[str, Any] | None = None,
    remove: Mapping[str, Any] | None = None,
    note: str | None = None,
) -> BulkResult:
    """Apply ``set``/``add``/``remove`` to many records; every record is its own write
    unit, and all share one ``batch_id``."""
    spec = entity_spec(entity_type)
    if not spec.generic_api:
        raise NotFoundError("Unknown entity type")
    clean = clean_note(note)
    problems = Problems()
    _check_bulk_ids(ids, problems)
    operations = _parse_bulk_operations(
        spec, {"set": set_values or {}, "add": add or {}, "remove": remove or {}}, clean, problems
    )
    if not any(operations.values()):
        problems.add("set", "At least one operation is required")
    problems.raise_if_any()
    batch_id = new_batch_id()
    results = [
        _bulk_item(session, spec, actor, entity_id, operations, clean, batch_id)
        for entity_id in ids
    ]
    return BulkResult(batch_id=batch_id, results=results)


def _bulk_item(
    session: Session,
    spec: EntityTypeSpec,
    actor: Actor,
    entity_id: str,
    operations: Mapping[str, Mapping[str, Any]],
    note: str | None,
    batch_id: str,
) -> BulkItemResult:
    try:
        with write_transaction(session):
            unit = WriteUnit.open(session, spec, actor)
            row = load_row(session, spec, entity_id)
            if row is None:
                return BulkItemResult(entity_id, "error", error=NotFoundError().to_dict())
            if row["deleted_at"] is not None:
                return BulkItemResult(entity_id, "entity_deleted", version=int(row["version"]))
            current = stored_values(spec, row, links_of(unit, row))
            changes = dict(operations["set"])
            for name, values in operations["add"].items():
                merged = list(current[name])
                merged.extend(value for value in values if value not in merged)
                changes[name] = merged
            for name, values in operations["remove"].items():
                changes[name] = [value for value in current[name] if value not in values]
            result = update_record(unit, row, changes, note=note, batch_id=batch_id)
            status = "updated" if result.changed else "unchanged"
            return BulkItemResult(entity_id, status, version=result.version)
    except DomainError as exc:
        return BulkItemResult(entity_id, "error", error=exc.to_dict())
