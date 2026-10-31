"""Source observations: what a collector saw per stable key, and the binding of keys to
records (docs/DATA_MODEL.md §14.5, §15.7; docs/API.md §7.5).

* :func:`upsert_observation` and :func:`bind_observation` run inside the reconciler's write
  units; :func:`record_sighting` (``ctx.observe``) is its own small write unit.
* :func:`disappearance_step` runs after a run with a complete listing that was not
  cancelled: keys the run did not see become missing, and live projects and services whose
  keys are all missing long enough get a ``possibly_discontinued`` proposal.
* Runs follow ``merged_into`` (:func:`resolve_subject`); an observation of a merged record
  keeps its ``subject_id`` (:func:`merged_into_ids` finds them for the survivor).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import ColumnElement, Table, func, insert, or_, select, update
from sqlalchemy.orm import Session

from mdt.db.models import Proposal, SourceObservation
from mdt.db.session import write_transaction
from mdt.domain.clock import utc_now
from mdt.domain.proposals import ProposalDraft, raise_proposal, supersede_where
from mdt.domain.records import Row, api_value, load_row, table_of
from mdt.domain.registry import ENTITY_TYPES, type_of_id
from mdt.domain.run_effects import RunEffects
from mdt.domain.text import fold

if TYPE_CHECKING:
    from mdt.collectors.base import RunScope

#: Reason of the ``possibly_discontinued`` proposals of DATA_MODEL §15.7.
MISSING_FROM_LISTING: Final = "missing_from_listing"
#: The status a ``possibly_discontinued`` proposal suggests (DATA_MODEL §16.1).
DISCONTINUED: Final = "discontinued"
#: The types that can get ``possibly_discontinued`` proposals.
DISCONTINUABLE_TYPES: Final = ("project", "service")
#: Longest merge chain followed (merges never form cycles; this only guards the loop).
_MAX_MERGE_DEPTH: Final = 100


def _table() -> Table:
    table = SourceObservation.__table__
    assert isinstance(table, Table)
    return table


# --------------------------------------------------------------------------------------
# Merged records
# --------------------------------------------------------------------------------------


def resolve_subject(session: Session, subject_id: str) -> tuple[str, Row] | None:
    """The record a reference leads to: the record itself, or the survivor it was merged
    into (repeatedly). None if a record of the chain does not exist."""
    current = subject_id
    for _ in range(_MAX_MERGE_DEPTH):
        entity_type = type_of_id(current)
        if entity_type is None:
            return None
        row = load_row(session, ENTITY_TYPES[entity_type], current)
        if row is None:
            return None
        merged_into = row.get("merged_into")
        if not merged_into:
            return current, row
        current = str(merged_into)
    return None


def merged_into_ids(session: Session, record_id: str) -> list[str]:
    """The record and every record merged into it, directly or through earlier merges."""
    entity_type = type_of_id(record_id)
    if entity_type is None or not ENTITY_TYPES[entity_type].curated:
        return [record_id]
    records = table_of(ENTITY_TYPES[entity_type])
    found = [record_id]
    frontier = [record_id]
    while frontier:
        merged = [
            str(entity_id)
            for entity_id in session.execute(
                select(records.c.id).where(records.c.merged_into.in_(frontier))
            ).scalars()
            if entity_id not in found
        ]
        found.extend(merged)
        frontier = merged
    return found


# --------------------------------------------------------------------------------------
# Upserts inside write units
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SeenObservation:
    """The state of an observation after a run saw its key."""

    id: int
    subject_id: str | None
    bound_by: str | None
    created: bool
    was_missing: bool


def find_observation(session: Session, collector: str, key: str) -> Row | None:
    """The observation of ``(collector, key)``, or None."""
    table = _table()
    row = (
        session.execute(select(table).where(table.c.collector == collector, table.c.key == key))
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def upsert_observation(
    session: Session,
    *,
    collector: str,
    run_id: str,
    entity_type: str,
    key: str,
    now: str,
    effects: RunEffects,
    url: str | None = None,
    label: str | None = None,
    external_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    snapshot_id: str | None = None,
) -> SeenObservation:
    """Record that run ``run_id`` saw ``key`` (DATA_MODEL §15.7): present, last seen now,
    no longer missing; ``url``, ``label``, ``external_id`` and ``last_snapshot_id`` are
    replaced when given, ``details`` are merged into the stored ones. A new key is inserted
    unbound with ``first_seen_*`` = ``last_seen_*``."""
    table = _table()
    row = find_observation(session, collector, key)
    if row is None:
        result = session.execute(
            insert(table)
            .values(
                collector=collector,
                key=key,
                entity_type=entity_type,
                external_id=external_id,
                url=url,
                label=label,
                first_seen_at=now,
                first_seen_run=run_id,
                last_seen_at=now,
                last_seen_run=run_id,
                present=True,
                missing_runs=0,
                last_snapshot_id=snapshot_id,
                details=dict(details or {}),
            )
            .returning(table.c.id)
        )
        effects.count("observations_new")
        return SeenObservation(int(result.scalar_one()), None, None, True, False)
    values: dict[str, Any] = {
        "last_seen_at": now,
        "last_seen_run": run_id,
        "present": True,
        "missing_runs": 0,
        "missing_since_at": None,
        "missing_since_run": None,
    }
    for name, value in (
        ("url", url),
        ("label", label),
        ("external_id", external_id),
        ("last_snapshot_id", snapshot_id),
    ):
        if value is not None:
            values[name] = value
    if details:
        values["details"] = {**(row["details"] or {}), **details}
    session.execute(update(table).where(table.c.id == row["id"]).values(**values))
    was_missing = not row["present"] or bool(row["missing_runs"])
    return SeenObservation(int(row["id"]), row["subject_id"], row["bound_by"], False, was_missing)


def bind_observation(
    session: Session, observation_id: int, subject_id: str, bound_by: str, now: str
) -> None:
    """Bind an observation to a record (``bound_by`` = ``auto`` or ``proposal``)."""
    table = _table()
    session.execute(
        update(table)
        .where(table.c.id == observation_id)
        .values(subject_id=subject_id, bound_by=bound_by, bound_at=now)
    )


def close_discontinued(
    session: Session,
    *,
    collector: str,
    subject_id: str,
    run_id: str,
    now: str,
    effects: RunEffects,
) -> None:
    """A key of the subject was seen again: its open ``possibly_discontinued`` proposals of
    this collector are superseded (DATA_MODEL §15.7)."""
    proposal = Proposal.__table__
    assert isinstance(proposal, Table)
    supersede_where(
        session,
        [
            proposal.c.kind == "possibly_discontinued",
            proposal.c.collector == collector,
            proposal.c.subject_id.in_(merged_into_ids(session, subject_id)),
        ],
        f"Seen again in run {run_id}",
        now=now,
        effects=effects,
    )


def note_seen(
    session: Session,
    seen: SeenObservation,
    *,
    collector: str,
    run_id: str,
    now: str,
    effects: RunEffects,
) -> None:
    """After an upsert: a key of a bound subject that was missing closes the subject's
    ``possibly_discontinued`` proposals of the collector."""
    if not seen.was_missing or seen.subject_id is None:
        return
    resolved = resolve_subject(session, seen.subject_id)
    subject_id = resolved[0] if resolved is not None else seen.subject_id
    close_discontinued(
        session,
        collector=collector,
        subject_id=subject_id,
        run_id=run_id,
        now=now,
        effects=effects,
    )


def record_sighting(
    session: Session,
    scope: RunScope,
    entity_type: str,
    key: str,
    *,
    url: str | None = None,
    label: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Upsert the observation of a key that was seen without being fetched (a listing or
    sitemap entry, or a page that yields no record): ``present = 1``, ``last_seen_*``,
    ``missing_*`` cleared; a new key is inserted unbound (DATA_MODEL §15.7). Its own small
    write unit."""
    effects = RunEffects()
    with write_transaction(session):
        now = utc_now()
        seen = upsert_observation(
            session,
            collector=scope.collector,
            run_id=scope.run_id,
            entity_type=entity_type,
            key=key,
            now=now,
            effects=effects,
            url=url,
            label=label,
            details=details,
        )
        note_seen(
            session,
            seen,
            collector=scope.collector,
            run_id=scope.run_id,
            now=now,
            effects=effects,
        )
    effects.report(scope)


# --------------------------------------------------------------------------------------
# Disappearance (DATA_MODEL §15.7)
# --------------------------------------------------------------------------------------


def disappearance_step(session: Session, scope: RunScope) -> None:
    """After a run with a complete listing that was not cancelled: every observation of
    the collector that the run did not see becomes missing, and live projects and services
    whose observations of a ``discontinued`` collector are all missing for
    ``scope.config.settings.discontinued_after_runs`` runs get a ``possibly_discontinued``
    proposal (DATA_MODEL §15.7)."""
    effects = RunEffects()
    with write_transaction(session):
        mark_missing(
            session, collector=scope.collector, run_id=scope.run_id, now=utc_now(), effects=effects
        )
    types = [
        entity_type
        for entity_type in DISCONTINUABLE_TYPES
        if (declaration := scope.declaration.get(entity_type)) is not None
        and declaration.discontinued
    ]
    if types:
        with write_transaction(session):
            raise_discontinued(
                session,
                collector=scope.collector,
                run_id=scope.run_id,
                entity_types=types,
                after_runs=scope.config.settings.discontinued_after_runs,
                now=utc_now(),
                effects=effects,
            )
    effects.report(scope)


def mark_missing(
    session: Session, *, collector: str, run_id: str, now: str, effects: RunEffects
) -> int:
    """Mark every observation of the collector that run ``run_id`` did not see as missing:
    ``present = 0``, ``missing_runs + 1`` and, if it was present, ``missing_since_*``."""
    table = _table()
    unseen = [table.c.collector == collector, table.c.last_seen_run != run_id]
    session.execute(
        update(table)
        .where(*unseen, table.c.present.is_(True))
        .values(missing_since_at=now, missing_since_run=run_id)
    )
    result = session.execute(
        update(table)
        .where(*unseen)
        .values(present=False, missing_runs=table.c.missing_runs + 1)
        .returning(table.c.id)
    )
    marked = len(result.all())
    effects.count("observations_missing", marked)
    return marked


def raise_discontinued(
    session: Session,
    *,
    collector: str,
    run_id: str,
    entity_types: Sequence[str],
    after_runs: int,
    now: str,
    effects: RunEffects,
) -> list[str]:
    """Raise a ``possibly_discontinued`` proposal for every live record of
    ``entity_types`` bound to observations of the collector (directly or through records
    merged into it) that are all missing for at least ``after_runs`` runs."""
    table = _table()
    rows = (
        session.execute(
            select(table)
            .where(
                table.c.collector == collector,
                table.c.entity_type.in_(list(entity_types)),
                table.c.subject_id.is_not(None),
            )
            .order_by(table.c.id)
        )
        .mappings()
        .all()
    )
    by_subject: dict[str, list[Mapping[str, Any]]] = {}
    subjects: dict[str, Row] = {}
    for row in rows:
        resolved = resolve_subject(session, str(row["subject_id"]))
        if resolved is None or resolved[1]["deleted_at"] is not None:
            continue
        by_subject.setdefault(resolved[0], []).append(dict(row))
        subjects[resolved[0]] = resolved[1]
    raised: list[str] = []
    for subject_id, observations in sorted(by_subject.items()):
        if any(row["missing_runs"] < after_runs for row in observations):
            continue
        draft = _discontinued_draft(collector, subject_id, subjects[subject_id], observations)
        if draft is None:
            continue
        result = raise_proposal(session, draft, run_id=run_id, now=now, effects=effects)
        if result.proposal_id is not None:
            raised.append(result.proposal_id)
    return raised


def _discontinued_draft(
    collector: str, subject_id: str, record: Row, observations: Sequence[Mapping[str, Any]]
) -> ProposalDraft | None:
    entity_type = type_of_id(subject_id)
    if entity_type is None:
        return None
    status = api_value(ENTITY_TYPES[entity_type].field("status"), record)
    if status == DISCONTINUED:
        return None
    latest = max(observations, key=lambda row: (str(row["last_seen_at"]), int(row["id"])))
    missing_since = min(
        (str(row["missing_since_at"]) for row in observations if row["missing_since_at"]),
        default=None,
    )
    return ProposalDraft(
        kind="possibly_discontinued",
        entity_type=entity_type,
        collector=collector,
        target=subject_id,
        core=MISSING_FROM_LISTING,
        subject_id=subject_id,
        current_value=status,
        proposed_value={"status": DISCONTINUED},
        payload={
            "reason": MISSING_FROM_LISTING,
            "last_seen_at": latest["last_seen_at"],
            "missing_since_at": missing_since,
            "keys": sorted(str(row["key"]) for row in observations),
        },
        raw_snapshot_id=latest["last_snapshot_id"],
        source_url=latest["url"],
        observation_id=int(latest["id"]),
    )


# --------------------------------------------------------------------------------------
# Reading (API §7.5 and the detail items of API §2)
# --------------------------------------------------------------------------------------

#: Most observations listed in a record's detail item.
DETAIL_LIMIT: Final = 50


def observation_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """The ``Observation`` object of API §7.5."""
    return {
        "id": row["id"],
        "collector": row["collector"],
        "key": row["key"],
        "entity_type": row["entity_type"],
        "subject_id": row["subject_id"],
        "bound_by": row["bound_by"],
        "bound_at": row["bound_at"],
        "external_id": row["external_id"],
        "url": row["url"],
        "label": row["label"],
        "first_seen_at": row["first_seen_at"],
        "first_seen_run": row["first_seen_run"],
        "last_seen_at": row["last_seen_at"],
        "last_seen_run": row["last_seen_run"],
        "present": bool(row["present"]),
        "missing_since_at": row["missing_since_at"],
        "missing_runs": row["missing_runs"],
        "last_snapshot_id": row["last_snapshot_id"],
        "details": dict(row["details"] or {}),
    }


@dataclass(frozen=True)
class ObservationFilter:
    """The filters of ``GET /api/observations``."""

    collectors: Sequence[str] = ()
    entity_types: Sequence[str] = ()
    subject_id: str | None = None
    present: bool | None = None
    bound: bool | None = None
    q: str | None = None


def _conditions(session: Session, flt: ObservationFilter) -> list[ColumnElement[bool]]:
    table = _table()
    conditions: list[ColumnElement[bool]] = []
    if flt.collectors:
        conditions.append(table.c.collector.in_(list(flt.collectors)))
    if flt.entity_types:
        conditions.append(table.c.entity_type.in_(list(flt.entity_types)))
    if flt.subject_id:
        conditions.append(table.c.subject_id.in_(merged_into_ids(session, flt.subject_id)))
    if flt.present is not None:
        conditions.append(table.c.present.is_(flt.present))
    if flt.bound is not None:
        bound = table.c.subject_id.is_not(None)
        conditions.append(bound if flt.bound else table.c.subject_id.is_(None))
    if flt.q:
        needle = fold(flt.q)
        conditions.append(
            or_(
                *(
                    func.instr(func.mdt_fold(table.c[name]), needle) > 0
                    for name in ("key", "label", "url")
                )
            )
        )
    return conditions


def list_observations(
    session: Session, flt: ObservationFilter, *, offset: int, limit: int
) -> tuple[list[dict[str, Any]], int]:
    """Observations under the filters, ordered by collector and key, and their total
    (inside the caller's read transaction)."""
    table = _table()
    conditions = _conditions(session, flt)
    total = session.execute(select(func.count()).select_from(table).where(*conditions)).scalar()
    rows = session.execute(
        select(table)
        .where(*conditions)
        .order_by(table.c.collector, table.c.key)
        .offset(offset)
        .limit(limit)
    ).mappings()
    return [observation_payload(dict(row)) for row in rows], int(total or 0)


def observations_of_record(session: Session, record_id: str) -> list[dict[str, Any]]:
    """The observations bound to the record or to records merged into it (at most
    :data:`DETAIL_LIMIT`), for its detail item."""
    items, _ = list_observations(
        session, ObservationFilter(subject_id=record_id), offset=0, limit=DETAIL_LIMIT
    )
    return items
