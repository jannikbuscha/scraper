"""Reading proposals (docs/API.md §7.4): the list with filters, the summary with the pattern
precision of ``create_event`` proposals, and the detail with both texts of a text-version
proposal. Every public function opens its own read transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import ColumnElement, Table, func, or_, select
from sqlalchemy.orm import Session

from mdt.db.models import Proposal
from mdt.db.session import read_transaction
from mdt.domain.document_versions import stored_text
from mdt.domain.errors import NotFoundError
from mdt.domain.labels import refs_payload
from mdt.domain.records import Row, load_links, load_row, stored_values
from mdt.domain.registry import ENTITY_TYPES, type_of_id

#: Sort orders of ``GET /api/proposals``; the first is the default.
SORTS: Final = ("-last_seen_at", "last_seen_at", "-created_at", "created_at")
DECIDED_STATES: Final = ("accepted", "accepted_modified", "rejected")


def _table() -> Table:
    table = Proposal.__table__
    assert isinstance(table, Table)
    return table


# --------------------------------------------------------------------------------------
# Representation
# --------------------------------------------------------------------------------------


def live_value(session: Session, proposal: Mapping[str, Any]) -> Any:
    """The subject's current value of the proposal's field (``update_field``) or status
    (``possibly_discontinued``), read now; None for the other kinds."""
    kind = proposal["kind"]
    if kind not in ("update_field", "possibly_discontinued") or not proposal["subject_id"]:
        return None
    entity_type = type_of_id(proposal["subject_id"])
    if entity_type is None:
        return None
    spec = ENTITY_TYPES[entity_type]
    name = proposal["field"] if kind == "update_field" else "status"
    if not name or not spec.has_field(name):
        return None
    row = load_row(session, spec, proposal["subject_id"])
    if row is None:
        return None
    links = load_links(session, [row["id"]])[row["id"]] if name == "links" else None
    return stored_values(spec, row, links)[name]


def proposal_payload(row: Mapping[str, Any], live: Any) -> dict[str, Any]:
    """The ``Proposal`` object of API §7.4."""
    return {
        "id": row["id"],
        "kind": row["kind"],
        "state": row["state"],
        "entity_type": row["entity_type"],
        "subject_id": row["subject_id"],
        "related_id": row["related_id"],
        "field": row["field"],
        "current_value": row["current_value"],
        "proposed_value": row["proposed_value"],
        "live_value": live,
        "payload": dict(row["payload"] or {}),
        "collector": row["collector"],
        "first_run_id": row["first_run_id"],
        "last_run_id": row["last_run_id"],
        "raw_snapshot_id": row["raw_snapshot_id"],
        "source_url": row["source_url"],
        "quote": row["quote"],
        "locator": row["locator"],
        "observation_id": row["observation_id"],
        "seen_count": row["seen_count"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "decided_at": row["decided_at"],
        "decided_by": row["decided_by"],
        "decision_note": row["decision_note"],
        "result_id": row["result_id"],
    }


def referenced_ids(row: Mapping[str, Any]) -> list[str]:
    """The record IDs a proposal mentions: subject, related record, result, the
    ``create_entity`` candidates, the event subject and the cited document."""
    payload = row["payload"] or {}
    ids = [row["subject_id"], row["related_id"], row["result_id"]]
    ids.extend(payload.get("candidates") or [])
    ids.append((payload.get("event") or {}).get("subject_id"))
    ids.append((payload.get("evidence") or {}).get("document_id"))
    return [entity_id for entity_id in ids if isinstance(entity_id, str) and entity_id]


def serialize_proposals(
    session: Session, rows: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Proposal objects with their live values, and the ``refs`` of the records they
    mention (inside the caller's transaction)."""
    items = [proposal_payload(row, live_value(session, row)) for row in rows]
    refs = refs_payload(session, [entity_id for row in rows for entity_id in referenced_ids(row)])
    return items, refs


# --------------------------------------------------------------------------------------
# List and summary
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposalFilter:
    """The filters of ``GET /api/proposals``; empty ``states`` means every state."""

    states: Sequence[str] = ("open",)
    kinds: Sequence[str] = ()
    collectors: Sequence[str] = ()
    entity_types: Sequence[str] = ()
    subject_id: str | None = None
    run_id: str | None = None
    field: str | None = None


def _conditions(flt: ProposalFilter) -> list[ColumnElement[bool]]:
    table = _table()
    conditions: list[ColumnElement[bool]] = []
    for column, values in (
        (table.c.state, flt.states),
        (table.c.kind, flt.kinds),
        (table.c.collector, flt.collectors),
        (table.c.entity_type, flt.entity_types),
    ):
        if values:
            conditions.append(column.in_(list(values)))
    if flt.subject_id:
        conditions.append(
            or_(table.c.subject_id == flt.subject_id, table.c.related_id == flt.subject_id)
        )
    if flt.run_id:
        conditions.append(
            or_(table.c.first_run_id == flt.run_id, table.c.last_run_id == flt.run_id)
        )
    if flt.field:
        conditions.append(table.c.field == flt.field)
    return conditions


def list_proposals(
    session: Session, flt: ProposalFilter, *, sort: str, offset: int, limit: int
) -> tuple[list[dict[str, Any]], int, dict[str, dict[str, Any]]]:
    """Proposals under the filters in the requested order, their total and ``refs``."""
    table = _table()
    descending = sort.startswith("-")
    column = table.c[sort.lstrip("-")]
    order = [column.desc(), table.c.id.desc()] if descending else [column.asc(), table.c.id.asc()]
    conditions = _conditions(flt)
    with read_transaction(session):
        total = session.execute(select(func.count()).select_from(table).where(*conditions)).scalar()
        rows = [
            dict(row)
            for row in session.execute(
                select(table).where(*conditions).order_by(*order).offset(offset).limit(limit)
            ).mappings()
        ]
        items, refs = serialize_proposals(session, rows)
    return items, int(total or 0), refs


def open_proposal_count(session: Session) -> int:
    """The number of open proposals (inside the caller's transaction)."""
    table = _table()
    count = session.execute(
        select(func.count()).select_from(table).where(table.c.state == "open")
    ).scalar()
    return int(count or 0)


def proposal_summary(session: Session) -> dict[str, Any]:
    """``GET /api/proposals/summary``: open proposals by kind, collector and type, and per
    event pattern the decisions on its ``create_event`` proposals with their precision."""
    table = _table()
    open_ = table.c.state == "open"
    with read_transaction(session):
        groups: dict[str, dict[str, int]] = {}
        for key, column in (
            ("by_kind", table.c.kind),
            ("by_collector", table.c.collector),
            ("by_entity_type", table.c.entity_type),
        ):
            groups[key] = {
                str(value): int(count)
                for value, count in session.execute(
                    select(column, func.count()).where(open_).group_by(column).order_by(column)
                )
            }
        pattern = func.json_extract(table.c.payload, "$.pattern_id")
        counts: dict[str, dict[str, int]] = {}
        for pattern_id, state, count in session.execute(
            select(pattern, table.c.state, func.count())
            .where(table.c.kind == "create_event", pattern.is_not(None))
            .group_by(pattern, table.c.state)
        ):
            counts.setdefault(str(pattern_id), {})[str(state)] = int(count)
        total = open_proposal_count(session)
    return {
        "open": total,
        **groups,
        "patterns": [_pattern_row(pattern_id, counts[pattern_id]) for pattern_id in sorted(counts)],
    }


def _pattern_row(pattern_id: str, states: Mapping[str, int]) -> dict[str, Any]:
    accepted = states.get("accepted", 0)
    modified = states.get("accepted_modified", 0)
    rejected = states.get("rejected", 0)
    decided = accepted + modified + rejected
    return {
        "pattern_id": pattern_id,
        "open": states.get("open", 0),
        "accepted": accepted,
        "accepted_modified": modified,
        "rejected": rejected,
        "precision": (accepted + modified) / decided if decided else None,
    }


# --------------------------------------------------------------------------------------
# Detail
# --------------------------------------------------------------------------------------


def _texts(session: Session, row: Row) -> dict[str, Any] | None:
    """Both texts of a text-version proposal (the document's live text and the proposed
    one), else None."""
    if row["kind"] != "update_field" or row["field"] != "text_hash":
        return None
    current = live_value(session, row)
    return {
        "current": stored_text(session, current if isinstance(current, str) else None),
        "proposed": stored_text(session, row["proposed_value"]),
    }


def proposal_detail(session: Session, proposal_id: str) -> dict[str, Any]:
    """``GET /api/proposals/{id}``: the proposal, its ``refs`` and ``texts``."""
    table = _table()
    with read_transaction(session):
        found = session.execute(select(table).where(table.c.id == proposal_id)).mappings().first()
        if found is None:
            raise NotFoundError("No such proposal")
        row = dict(found)
        items, refs = serialize_proposals(session, [row])
        return {"proposal": items[0], "refs": refs, "texts": _texts(session, row)}


def proposal_item(session: Session, proposal_id: str) -> dict[str, Any]:
    """One ``Proposal`` object (for write responses), in its own read transaction."""
    return dict(proposal_detail(session, proposal_id)["proposal"])
