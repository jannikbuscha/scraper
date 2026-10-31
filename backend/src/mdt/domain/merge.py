"""Merging duplicate projects and services (docs/DATA_MODEL.md §18; docs/API.md §7.6).

:func:`merge` folds a merged record into a survivor in one transaction with one
``batch_id`` on channel ``merge``: the survivor takes the field values the person chose,
the references held in editable fields move to the survivor (document links merged), the
merged record is soft-deleted with ``merged_into``, its open proposals are superseded, and
``merge_log`` records every change with its before and after value. Evidence, comments and
observations stay where they are. :func:`unmerge` reverses a merge the same way, leaving
references that changed afterwards as they are. :func:`merge_preview` shows what a merge
would do, including the conflicts that refuse it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import Table, insert, or_, select, update
from sqlalchemy.orm import Session

from mdt.db.models import DocumentLink, MergeLog, Proposal, Relation, Service
from mdt.db.session import read_transaction, write_transaction
from mdt.domain import derived
from mdt.domain.actor import Actor
from mdt.domain.errors import (
    InvalidStateError,
    MergeConflictError,
    NotFoundError,
    Problems,
    ValidationError,
)
from mdt.domain.ids import new_batch_id, new_id
from mdt.domain.labels import ref_info
from mdt.domain.normalize import INVALID, normalize_value, values_equal
from mdt.domain.proposals import supersede_for_subject
from mdt.domain.records import Row, load_links, load_row, stored_values, table_of
from mdt.domain.registry import ENTITY_TYPES, EntityTypeSpec, FieldSpec, type_of_id
from mdt.domain.writes import (
    WriteUnit,
    clean_note,
    normalize_changes,
    update_record,
    write_state_change,
)

MERGEABLE_TYPES: Final = ("project", "service")
CHOICES: Final = ("survivor", "merged", "union")
#: Link states, strongest first, for a document that links both records (§18).
_LINK_STRENGTH: Final = {"confirmed": 3, "rejected": 2, "suggested": 1}
#: References held in editable fields: (type, field) per merged type.
_REFERENCES: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "project": (
        ("service", "project_id"),
        ("event", "subject_id"),
        ("participation", "subject_id"),
        ("relation", "from_id"),
        ("relation", "to_id"),
        ("indicator", "subject_id"),
    ),
    "service": (
        ("service", "parent_service_id"),
        ("event", "subject_id"),
        ("participation", "subject_id"),
        ("relation", "from_id"),
        ("relation", "to_id"),
        ("indicator", "subject_id"),
    ),
}


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def mergeable_spec(entity_type: str) -> EntityTypeSpec:
    """The registry entry of a type that can be merged (400 for any other type)."""
    if entity_type not in MERGEABLE_TYPES:
        raise ValidationError.single("type", "Only projects and services can be merged")
    return ENTITY_TYPES[entity_type]


def choice_fields(spec: EntityTypeSpec) -> list[FieldSpec]:
    """The fields whose value the person chooses: tracked, editable, not create-only."""
    return [field_spec for field_spec in spec.tracked_fields if field_spec.restorable]


# --------------------------------------------------------------------------------------
# Planning (shared by the preview and the merge)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Repoint:
    """One reference to move: row ``id`` of ``entity_type`` holds the merged ID in
    ``field``."""

    entity_type: str
    id: str
    field: str


@dataclass
class _Plan:
    """What a merge of ``merged`` into ``survivor`` would move, and its conflicts."""

    survivor: Row
    merged: Row
    repoints: list[_Repoint] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Rows to change per type (a row with two references counts once)."""
        rows: dict[str, set[str]] = {}
        for repoint in self.repoints:
            rows.setdefault(repoint.entity_type, set()).add(repoint.id)
        counts = {
            entity_type: len(rows.get(entity_type, set()))
            for entity_type in ("service", "event", "participation", "relation", "indicator")
        }
        counts["document"] = len(self.documents)
        return counts


def _load_pair(
    session: Session, spec: EntityTypeSpec, survivor_id: str, merged_id: str
) -> tuple[Row, Row]:
    """Both records exist (404), are distinct, of the type and live (409 otherwise)."""
    rows = []
    for record_id in (survivor_id, merged_id):
        row = load_row(session, spec, record_id) if type_of_id(record_id) == spec.name else None
        if row is None:
            raise NotFoundError(f"No {spec.label.lower()} {record_id}")
        rows.append(row)
    survivor, merged = rows
    if survivor_id == merged_id:
        raise InvalidStateError("same", "A record cannot be merged into itself")
    for row in (survivor, merged):
        if row["deleted_at"] is not None:
            state = "merged" if row["merged_into"] else "deleted"
            raise InvalidStateError(state, "Both records must be live to be merged")
    return survivor, merged


def _conflict(session: Session, kind: str, entity_id: str, message: str) -> dict[str, Any]:
    info = ref_info(session, entity_id)
    return {
        "kind": kind,
        "id": entity_id,
        "label": info.label if info else entity_id,
        "message": message,
    }


def _plan(session: Session, spec: EntityTypeSpec, survivor: Row, merged: Row) -> _Plan:
    """The references to move (live rows only; deleted rows keep theirs) and the
    conflicts that refuse the merge (§18)."""
    plan = _Plan(survivor, merged)
    survivor_id, merged_id = survivor["id"], merged["id"]
    for entity_type, name in _REFERENCES[spec.name]:
        table = table_of(ENTITY_TYPES[entity_type])
        for (entity_id,) in session.execute(
            select(table.c.id)
            .where(table.c[name] == merged_id, table.c.deleted_at.is_(None))
            .order_by(table.c.id)
        ):
            plan.repoints.append(_Repoint(entity_type, str(entity_id), name))
    documents = _table(DocumentLink)
    document_table = table_of(ENTITY_TYPES["document"])
    plan.documents = [
        str(document_id)
        for document_id in session.execute(
            select(documents.c.document_id)
            .join(document_table, document_table.c.id == documents.c.document_id)
            .where(documents.c.subject_id == merged_id, document_table.c.deleted_at.is_(None))
            .order_by(documents.c.document_id)
        ).scalars()
    ]
    relations = _table(Relation)
    for (relation_id,) in session.execute(
        select(relations.c.id).where(
            relations.c.deleted_at.is_(None),
            or_(
                (relations.c.from_id == survivor_id) & (relations.c.to_id == merged_id),
                (relations.c.from_id == merged_id) & (relations.c.to_id == survivor_id),
            ),
        )
    ):
        plan.conflicts.append(
            _conflict(
                session,
                "relation",
                str(relation_id),
                "This relation between the two records would point to itself",
            )
        )
    if spec.name == "service":
        _service_conflicts(session, plan)
    else:
        _project_conflicts(session, plan)
    return plan


def _service_conflicts(session: Session, plan: _Plan) -> None:
    """The merged service's children get the survivor as parent: it must lie in their
    project, and must not descend from them (a cycle)."""
    survivor = plan.survivor
    ancestors = set()
    current = survivor["parent_service_id"]
    services = _table(Service)
    while current and current not in ancestors:
        ancestors.add(current)
        current = session.execute(
            select(services.c.parent_service_id).where(services.c.id == current)
        ).scalar()
    for repoint in plan.repoints:
        if repoint.field != "parent_service_id":
            continue
        child = load_row(session, ENTITY_TYPES["service"], repoint.id)
        assert child is not None
        if child["id"] == survivor["id"] or child["id"] in ancestors:
            plan.conflicts.append(
                _conflict(
                    session,
                    "service",
                    child["id"],
                    "Taking the survivor as parent would create a cycle",
                )
            )
        elif child["project_id"] != survivor["project_id"]:
            plan.conflicts.append(
                _conflict(
                    session,
                    "service",
                    child["id"],
                    "The survivor lies in another project than this child service",
                )
            )


def _project_conflicts(session: Session, plan: _Plan) -> None:
    """The merged project's services move to the survivor with their parents; a service
    whose parent stays behind (deleted) would end up in another project than its parent."""
    services = _table(Service)
    moving = {repoint.id for repoint in plan.repoints if repoint.field == "project_id"}
    for repoint in plan.repoints:
        if repoint.field != "project_id":
            continue
        parent = session.execute(
            select(services.c.parent_service_id).where(services.c.id == repoint.id)
        ).scalar()
        if parent and parent not in moving:
            plan.conflicts.append(
                _conflict(
                    session,
                    "service",
                    repoint.id,
                    "Its parent service is deleted and would stay in the merged project",
                )
            )


# --------------------------------------------------------------------------------------
# Field choices
# --------------------------------------------------------------------------------------


def _parse_choices(spec: EntityTypeSpec, choices: Mapping[str, Any] | None) -> dict[str, str]:
    allowed = {field_spec.name: field_spec for field_spec in choice_fields(spec)}
    problems = Problems()
    parsed: dict[str, str] = {}
    for name, choice in (choices or {}).items():
        path = f"fields.{name}"
        if name not in allowed:
            problems.add(path, "is not a field whose value can be chosen")
        elif choice not in CHOICES:
            problems.add(path, f"must be one of {', '.join(CHOICES)}")
        elif choice == "union" and not allowed[name].is_list:
            problems.add(path, "union is only possible for list fields")
        elif choice != "survivor":
            parsed[name] = str(choice)
    problems.raise_if_any()
    return parsed


def _chosen_values(
    spec: EntityTypeSpec,
    survivor: Mapping[str, Any],
    merged: Mapping[str, Any],
    choices: Mapping[str, str],
) -> dict[str, Any]:
    """The survivor's new values: the merged record's value, or the union of both lists
    (the survivor's items, then the merged record's items not yet present)."""
    values: dict[str, Any] = {}
    problems = Problems()
    for name, choice in choices.items():
        field_spec = spec.field(name)
        value = (
            [*survivor[name], *merged[name]] if choice == "union" else copy.deepcopy(merged[name])
        )
        normalized = normalize_value(field_spec, value, problems, f"fields.{name}")
        if normalized is not INVALID and not values_equal(field_spec, survivor[name], normalized):
            values[name] = normalized
    problems.raise_if_any()
    if "in_paper_scope" in values and "scope_note" not in values:
        values["scope_note"] = survivor.get("scope_note")
    return values


# --------------------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------------------


def merge_preview(
    session: Session, entity_type: str, survivor_id: str, merged_id: str
) -> dict[str, Any]:
    """``GET …/merge-preview``: the differing fields with both values, the references to
    move per type and the conflicts."""
    spec = mergeable_spec(entity_type)
    with read_transaction(session):
        survivor, merged = _load_pair(session, spec, survivor_id, merged_id)
        plan = _plan(session, spec, survivor, merged)
        survivor_values = stored_values(spec, survivor)
        merged_values = stored_values(spec, merged)
        fields = [
            {
                "name": field_spec.name,
                "survivor": survivor_values[field_spec.name],
                "merged": merged_values[field_spec.name],
                "list": field_spec.is_list,
                "default": "survivor",
            }
            for field_spec in choice_fields(spec)
            if not values_equal(
                field_spec, survivor_values[field_spec.name], merged_values[field_spec.name]
            )
        ]
        return {"fields": fields, "repoint": plan.counts(), "conflicts": plan.conflicts}


# --------------------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeResult:
    """Outcome of a merge or unmerge."""

    merge_id: str
    batch_id: str
    record_id: str
    revision_ids: list[int]
    skipped: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Writer:
    """The write context of one merge or unmerge: one actor, timestamp and batch."""

    session: Session
    actor: Actor
    batch_id: str
    action: str
    units: dict[str, WriteUnit] = field(default_factory=dict)
    revision_ids: list[int] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)

    def unit(self, entity_type: str) -> WriteUnit:
        """The write unit context of ``entity_type`` (one timestamp for the whole action)."""
        if entity_type not in self.units:
            spec = ENTITY_TYPES[entity_type]
            first = next(iter(self.units.values()), None)
            self.units[entity_type] = (
                first.for_type(spec) if first else WriteUnit.open(self.session, spec, self.actor)
            )
        return self.units[entity_type]

    def update(
        self,
        entity_type: str,
        row: Row,
        values: Mapping[str, Any],
        *,
        note: str | None,
        moving: Mapping[str, str] | None = None,
    ) -> bool:
        """Write ``values`` to a live row (one revision); True if anything changed."""
        unit = self.unit(entity_type)
        provided = normalize_changes(unit, dict(values), creating=False)
        result = update_record(
            unit,
            row,
            provided,
            note=note,
            batch_id=self.batch_id,
            action=self.action,
            moving_services=moving,
        )
        if result.changed and result.revision_id is not None:
            self.revision_ids.append(result.revision_id)
        return result.changed


def merge(
    session: Session,
    entity_type: str,
    survivor_id: str,
    merged_id: str,
    field_choices: Mapping[str, Any] | None,
    note: str | None,
    proposal_id: str | None = None,
) -> MergeResult:
    """Merge ``merged_id`` into ``survivor_id`` (DATA_MODEL §18), all or nothing;
    ``409 merge_conflict`` with the conflicts if repointing would break a rule."""
    spec = mergeable_spec(entity_type)
    clean = clean_note(note)
    choices = _parse_choices(spec, field_choices)
    with write_transaction(session):
        survivor, merged = _load_pair(session, spec, survivor_id, merged_id)
        if proposal_id is not None:
            _check_proposal(session, proposal_id, survivor_id, merged_id)
        plan = _plan(session, spec, survivor, merged)
        if plan.conflicts:
            raise MergeConflictError(plan.conflicts)
        writer = _Writer(session, Actor.merge(proposal_id), new_batch_id(), "merge")
        survivor_values = stored_values(spec, survivor)
        values = _chosen_values(spec, survivor_values, stored_values(spec, merged), choices)
        if writer.update(spec.name, survivor, values, note=clean):
            writer.changes.extend(
                {
                    "entity_type": spec.name,
                    "id": survivor_id,
                    "field": name,
                    "before": survivor_values[name],
                    "after": value,
                }
                for name, value in values.items()
            )
        _move_references(writer, plan, survivor_id, merged_id, clean)
        _move_links(writer, plan.documents, survivor_id, merged_id, clean)
        merged_row = load_row(session, spec, merged_id)
        assert merged_row is not None
        result = write_state_change(
            writer.unit(spec.name),
            merged_row,
            action="merge",
            note=clean,
            batch_id=writer.batch_id,
            deleted=True,
            merged_into=survivor_id,
        )
        assert result.revision_id is not None
        writer.revision_ids.append(result.revision_id)
        now = writer.unit(spec.name).ts
        keep = [proposal_id] if proposal_id else []
        supersede_for_subject(session, merged_id, f"Merged into {survivor_id}", now=now, keep=keep)
        if proposal_id is not None:
            _accept_proposal(session, proposal_id, survivor_id, clean, now)
        merge_id = new_id("mrg")
        session.execute(
            insert(_table(MergeLog)).values(
                id=merge_id,
                entity_type=spec.name,
                survivor_id=survivor_id,
                merged_id=merged_id,
                at=now,
                batch_id=writer.batch_id,
                proposal_id=proposal_id,
                note=clean,
                field_choices=choices,
                changes=writer.changes,
            )
        )
        settings = writer.unit(spec.name).settings
        derived.recompute(session, [survivor_id, merged_id], now, settings)
        return MergeResult(merge_id, writer.batch_id, survivor_id, writer.revision_ids)


def _move_references(
    writer: _Writer, plan: _Plan, survivor_id: str, merged_id: str, note: str | None
) -> None:
    """Point every reference to the merged record at the survivor, one revision per row;
    the merged project's services move as one family."""
    by_row: dict[tuple[str, str], list[str]] = {}
    for repoint in plan.repoints:
        by_row.setdefault((repoint.entity_type, repoint.id), []).append(repoint.field)
    moving = {repoint.id: survivor_id for repoint in plan.repoints if repoint.field == "project_id"}
    for (entity_type, entity_id), names in by_row.items():
        row = load_row(writer.session, ENTITY_TYPES[entity_type], entity_id)
        assert row is not None
        values = dict.fromkeys(names, survivor_id)
        if writer.update(entity_type, row, values, note=note, moving=moving):
            writer.changes.extend(
                {
                    "entity_type": entity_type,
                    "id": entity_id,
                    "field": name,
                    "before": merged_id,
                    "after": survivor_id,
                }
                for name in names
            )


def _merged_link(first: Mapping[str, Any], second: Mapping[str, Any] | None) -> dict[str, Any]:
    """One link instead of two: the stronger state, origin manual if either was manual."""
    if second is None:
        return dict(first)
    stronger = max((first, second), key=lambda link: _LINK_STRENGTH.get(link["state"], 0))
    origin = "manual" if "manual" in (first["origin"], second["origin"]) else stronger["origin"]
    return {**stronger, "origin": origin}


def _move_links(
    writer: _Writer, documents: Sequence[str], survivor_id: str, merged_id: str, note: str | None
) -> None:
    """Move document links from the merged record to the survivor (a document that links
    both keeps one link, §18)."""
    spec = ENTITY_TYPES["document"]
    for document_id in documents:
        row = load_row(writer.session, spec, document_id)
        assert row is not None
        links = load_links(writer.session, [document_id])[document_id]
        old = next(link for link in links if link["subject_id"] == merged_id)
        kept = next((link for link in links if link["subject_id"] == survivor_id), None)
        new = {**_merged_link(old, kept), "subject_id": survivor_id}
        others = [link for link in links if link["subject_id"] not in (merged_id, survivor_id)]
        if writer.update("document", row, {"links": [*others, new]}, note=note):
            writer.changes.append(
                {
                    "entity_type": "document",
                    "id": document_id,
                    "field": "links",
                    "before": {merged_id: old, survivor_id: kept},
                    "after": {survivor_id: new},
                }
            )


def _check_proposal(session: Session, proposal_id: str, survivor_id: str, merged_id: str) -> None:
    """The proposal a merge accepts is the open ``possible_duplicate`` of the pair."""
    table = _table(Proposal)
    row = session.execute(select(table).where(table.c.id == proposal_id)).mappings().first()
    if row is None:
        raise ValidationError.single("proposal_id", "No such proposal")
    if row["state"] != "open":
        raise InvalidStateError(str(row["state"]), "The proposal is not open")
    if row["kind"] != "possible_duplicate" or {row["subject_id"], row["related_id"]} != {
        survivor_id,
        merged_id,
    }:
        raise ValidationError.single(
            "proposal_id", "must name the possible_duplicate proposal of these two records"
        )


def _accept_proposal(
    session: Session, proposal_id: str, survivor_id: str, note: str | None, now: str
) -> None:
    table = _table(Proposal)
    session.execute(
        update(table)
        .where(table.c.id == proposal_id)
        .values(
            state="accepted",
            decided_at=now,
            decided_by=Actor.ui().by,
            decision_note=note,
            result_id=survivor_id,
        )
    )


# --------------------------------------------------------------------------------------
# Unmerge
# --------------------------------------------------------------------------------------


def unmerge(session: Session, entity_type: str, merged_id: str, note: str | None) -> MergeResult:
    """Reverse the latest merge of ``merged_id`` (DATA_MODEL §18): undelete it, move back
    every logged reference whose field still holds the logged value and restore the
    survivor's fields that still hold the merge's value; the rest is ``skipped``."""
    spec = mergeable_spec(entity_type)
    clean = clean_note(note)
    with write_transaction(session):
        merged = load_row(session, spec, merged_id) if type_of_id(merged_id) == spec.name else None
        if merged is None:
            raise NotFoundError()
        log = _latest_merge(session, merged_id)
        if merged["deleted_at"] is None or not merged["merged_into"] or log is None:
            state = "live" if merged["deleted_at"] is None else "deleted"
            raise InvalidStateError(state, "The record is not merged into another one")
        writer = _Writer(session, Actor.merge(), new_batch_id(), "unmerge")
        result = write_state_change(
            writer.unit(spec.name),
            merged,
            action="unmerge",
            note=clean,
            batch_id=writer.batch_id,
            deleted=False,
            merged_into=None,
        )
        assert result.revision_id is not None
        writer.revision_ids.append(result.revision_id)
        skipped = _reverse(writer, log["changes"], merged_id, clean)
        now = writer.unit(spec.name).ts
        session.execute(
            update(_table(MergeLog))
            .where(_table(MergeLog).c.id == log["id"])
            .values(unmerged_at=now, unmerge_batch_id=writer.batch_id)
        )
        settings = writer.unit(spec.name).settings
        derived.recompute(session, [log["survivor_id"], merged_id], now, settings)
        return MergeResult(log["id"], writer.batch_id, merged_id, writer.revision_ids, skipped)


def _latest_merge(session: Session, merged_id: str) -> Row | None:
    """The newest merge of the record that was not unmerged."""
    table = _table(MergeLog)
    row = (
        session.execute(
            select(table)
            .where(table.c.merged_id == merged_id, table.c.unmerged_at.is_(None))
            .order_by(table.c.at.desc(), table.c.id.desc())
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def _reverse(
    writer: _Writer, changes: Sequence[Mapping[str, Any]], merged_id: str, note: str | None
) -> list[dict[str, Any]]:
    """Undo the logged changes row by row where the field still holds the logged value."""
    skipped: list[dict[str, Any]] = []
    by_row: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for change in changes:
        by_row.setdefault((change["entity_type"], change["id"]), []).append(change)
    moving = {
        str(change["id"]): merged_id
        for change in changes
        if change["entity_type"] == "service" and change["field"] == "project_id"
    }
    for (entity_type, entity_id), row_changes in by_row.items():
        spec = ENTITY_TYPES[entity_type]
        row = load_row(writer.session, spec, entity_id)
        if row is None:
            continue
        links = (
            load_links(writer.session, [entity_id])[entity_id] if spec.has_field("links") else None
        )
        current = stored_values(spec, row, links)
        values: dict[str, Any] = {}
        for change in row_changes:
            name = change["field"]
            if name == "links":
                restored = _restored_links(current["links"], change)
                if restored is not None and row["deleted_at"] is None:
                    values["links"] = restored
                    continue
            elif row["deleted_at"] is None and values_equal(
                spec.field(name), current[name], change["after"]
            ):
                values[name] = change["before"]
                continue
            skipped.append(
                {
                    "entity_type": entity_type,
                    "id": entity_id,
                    "field": name,
                    "current": current[name],
                }
            )
        if values:
            writer.update(entity_type, row, values, note=note, moving=moving)
    return skipped


def _restored_links(
    current: Sequence[Mapping[str, Any]], change: Mapping[str, Any]
) -> list[dict[str, Any]] | None:
    """The links before the merge, if the document still has the merged link exactly as
    the merge left it; else None."""
    ((survivor_id, after),) = change["after"].items()
    now = next((link for link in current if link["subject_id"] == survivor_id), None)
    if now != after:
        return None
    others = [dict(link) for link in current if link["subject_id"] != survivor_id]
    before = [dict(link) for link in change["before"].values() if link is not None]
    return [*others, *before]
