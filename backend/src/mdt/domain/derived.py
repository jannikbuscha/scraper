"""Derived values of projects and services (docs/DATA_MODEL.md §8, CODEBOOK §2.7).

:func:`compute_derived` is a pure function of the subject's events and the focal
organisation's participations. The database functions keep exactly one ``derived`` row
per project and service and recompute it inside the write transaction that changed an
input. A row is only rewritten (and ``computed_at`` set) when a value changes.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from mdt.config import Settings
from mdt.db.models import AppState, Derived, Event, Organization, Participation, Project, Service
from mdt.domain.dates import EARLIEST_DATE, format_partial_date, parse_iso_date
from mdt.domain.registry import PeriodParameters, type_of_id
from mdt.domain.vocab import load_parameters, modification_event_types, parameters_digest

HASH_KEY = "derived_inputs_hash"
PORTFOLIO_ROLES = frozenset({"initiator", "owner", "operator"})
DERIVED_TYPES = ("project", "service")
_BATCH = 500


@dataclass(frozen=True)
class EventInput:
    """An event as input of the derived values (non-deleted, not disputed)."""

    id: str
    event_type: str
    start: date | None
    end: date | None
    precision: str | None
    basis: str | None

    @property
    def dated(self) -> bool:
        """True if the event has a date."""
        return self.start is not None and self.end is not None

    @property
    def interval(self) -> tuple[date, date]:
        """The date interval; archive upper bounds count as [1900-01-01, end] (§8.2)."""
        assert self.start is not None and self.end is not None
        if self.basis == "archive_upper_bound":
            return (EARLIEST_DATE, self.end)
        return (self.start, self.end)

    @property
    def value(self) -> str | None:
        """The canonical partial date."""
        if self.start is None or self.precision is None:
            return None
        return format_partial_date(self.start, self.precision)


@dataclass(frozen=True)
class ParticipationInput:
    """A participation of the focal organisation (non-deleted, not disputed)."""

    id: str
    role: str
    start: date | None
    end: date | None
    precision: str | None


@dataclass(frozen=True)
class DerivedValues:
    """The values of one ``derived`` row (without ``entity_id`` and ``computed_at``)."""

    launch_start: str | None = None
    launch_end: str | None = None
    launch_value: str | None = None
    launch_precision: str | None = None
    launch_basis: str | None = None
    launch_event_id: str | None = None
    existed_by: str | None = None
    existed_by_event_id: str | None = None
    existed_before_invasion: bool = False
    period: str = "unknown"
    period_reason: str | None = "no_date"
    war_trajectory: str = "unknown"
    trajectory_reason: str | None = "no_date"
    trajectory_event_id: str | None = None
    portfolio_entry_start: str | None = None
    portfolio_entry_end: str | None = None
    portfolio_entry_value: str | None = None
    portfolio_entry_precision: str | None = None
    portfolio_entry_participation_id: str | None = None

    def as_row(self) -> dict[str, Any]:
        """Column values."""
        return asdict(self)


#: The state of a new entity (§8.1).
INITIAL = DerivedValues()


def _period(
    launch: tuple[date, date] | None, existed_by: date | None, params: PeriodParameters
) -> tuple[str, str | None]:
    ministry, invasion = params.ministry_founded, params.full_scale_invasion
    if launch is not None:
        start, end = launch
        if end < ministry:
            return "pre_ministry", None
        if start >= ministry and end < invasion:
            return "pre_invasion", None
        if start >= invasion:
            return "full_scale_war", None
        return "unknown", "imprecise_date"
    if existed_by is not None:
        if existed_by < ministry:
            return "pre_ministry", None
        return "unknown", "archive_bound_only"
    return "unknown", "no_date"


def _trajectory(
    launch: tuple[date, date] | None,
    launch_event: EventInput | None,
    existed_by_event: EventInput | None,
    existed_before: bool,
    modifications: Sequence[EventInput],
    invasion: date,
) -> tuple[str, str | None, str | None]:
    """(war_trajectory, trajectory_reason, trajectory_event_id), rules 5.1-5.5."""
    if launch is not None and launch[0] >= invasion:
        if existed_before:
            # The launch is on or after the invasion, but an archive bound shows the item
            # existed before it; link the archive event.
            return "unknown", "conflicting_dates", existed_by_event.id if existed_by_event else None
        return "new_in_war", None, launch_event.id if launch_event else None
    if existed_before:
        after = [e for e in modifications if e.dated and e.interval[0] >= invasion]
        if after:
            first = min(after, key=lambda e: (e.interval[0], e.id))
            return "adapted_in_war", None, first.id
        if all(e.dated and e.interval[1] < invasion for e in modifications):
            return "prewar_unchanged", None, None
        imprecise = [
            e for e in modifications if not e.dated or (e.interval[0] < invasion <= e.interval[1])
        ]
        pick = min(
            imprecise, key=lambda e: (not e.dated, e.interval[0] if e.dated else date.max, e.id)
        )
        return "unknown", "imprecise_modification_date", pick.id
    if launch is not None:
        # The launch interval straddles the invasion.
        return "unknown", "imprecise_date", None
    if existed_by_event is not None:
        # Only an archive bound on or after the invasion: it does not tell new from old.
        return "unknown", "archive_bound_only", None
    return "unknown", "no_date", None


def compute_derived(
    events: Iterable[EventInput],
    participations: Iterable[ParticipationInput],
    modification_types: Iterable[str],
    params: PeriodParameters,
) -> DerivedValues:
    """Apply the rules of DATA_MODEL §8.3 to one subject's inputs."""
    all_events = list(events)
    dated = [event for event in all_events if event.dated]
    candidates = [e for e in dated if e.event_type == "launch"] or [
        e for e in dated if e.event_type == "beta_launch"
    ]
    launch: tuple[date, date] | None = None
    launch_event: EventInput | None = None
    if candidates:
        launch = (
            min(e.interval[0] for e in candidates),
            min(e.interval[1] for e in candidates),
        )
        launch_event = min(candidates, key=lambda e: (e.interval[1], e.interval[0], e.id))
    archived = [e for e in dated if e.event_type == "first_archived"]
    existed_by_event = (
        min(archived, key=lambda e: (e.interval[1], e.interval[0], e.id)) if archived else None
    )
    existed_by = existed_by_event.interval[1] if existed_by_event else None
    invasion = params.full_scale_invasion

    period, period_reason = _period(launch, existed_by, params)
    existed_before = bool(
        (launch is not None and launch[1] < invasion)
        or (existed_by is not None and existed_by < invasion)
    )
    modification_set = set(modification_types)
    modifications = [e for e in all_events if e.event_type in modification_set]
    trajectory, trajectory_reason, trajectory_event = _trajectory(
        launch, launch_event, existed_by_event, existed_before, modifications, invasion
    )

    entry_candidates = [
        p for p in participations if p.role in PORTFOLIO_ROLES and p.start is not None
    ]
    entry = (
        min(entry_candidates, key=lambda p: (p.start, p.end, p.id)) if entry_candidates else None
    )

    return DerivedValues(
        launch_start=launch[0].isoformat() if launch else None,
        launch_end=launch[1].isoformat() if launch else None,
        launch_value=launch_event.value if launch_event else None,
        launch_precision=launch_event.precision if launch_event else None,
        launch_basis=launch_event.basis if launch_event else None,
        launch_event_id=launch_event.id if launch_event else None,
        existed_by=existed_by.isoformat() if existed_by else None,
        existed_by_event_id=existed_by_event.id if existed_by_event else None,
        existed_before_invasion=existed_before,
        period=period,
        period_reason=period_reason,
        war_trajectory=trajectory,
        trajectory_reason=trajectory_reason,
        trajectory_event_id=trajectory_event,
        portfolio_entry_start=entry.start.isoformat() if entry and entry.start else None,
        portfolio_entry_end=entry.end.isoformat() if entry and entry.end else None,
        portfolio_entry_value=(
            format_partial_date(entry.start, entry.precision)
            if entry and entry.start and entry.precision
            else None
        ),
        portfolio_entry_precision=entry.precision if entry else None,
        portfolio_entry_participation_id=entry.id if entry else None,
    )


# --------------------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------------------


def _date(value: str | None) -> date | None:
    return parse_iso_date(value) if value else None


def focal_org_id(session: Session, settings: Settings) -> str | None:
    """ID of the focal organisation (``seed_key == FOCAL_ORG_SEED_KEY``), if seeded."""
    return session.execute(
        select(Organization.id).where(Organization.seed_key == settings.focal_org_seed_key)
    ).scalar()


def _load_events(session: Session, subject_ids: Sequence[str]) -> dict[str, list[EventInput]]:
    result: dict[str, list[EventInput]] = defaultdict(list)
    rows = session.execute(
        select(
            Event.id,
            Event.subject_id,
            Event.event_type,
            Event.date_start,
            Event.date_end,
            Event.date_precision,
            Event.date_basis,
        ).where(
            Event.subject_id.in_(subject_ids),
            Event.deleted_at.is_(None),
            Event.verification_status != "disputed",
        )
    )
    for row in rows:
        result[row.subject_id].append(
            EventInput(
                id=row.id,
                event_type=row.event_type,
                start=_date(row.date_start),
                end=_date(row.date_end),
                precision=row.date_precision,
                basis=row.date_basis,
            )
        )
    return result


def _load_participations(
    session: Session, subject_ids: Sequence[str], focal_id: str | None
) -> dict[str, list[ParticipationInput]]:
    result: dict[str, list[ParticipationInput]] = defaultdict(list)
    if focal_id is None:
        return result
    rows = session.execute(
        select(
            Participation.id,
            Participation.subject_id,
            Participation.role,
            Participation.start_start,
            Participation.start_end,
            Participation.start_precision,
        ).where(
            Participation.subject_id.in_(subject_ids),
            Participation.organization_id == focal_id,
            Participation.deleted_at.is_(None),
            Participation.verification_status != "disputed",
        )
    )
    for row in rows:
        result[row.subject_id].append(
            ParticipationInput(
                id=row.id,
                role=row.role,
                start=_date(row.start_start),
                end=_date(row.start_end),
                precision=row.start_precision,
            )
        )
    return result


def compute_for(
    session: Session, entity_ids: Sequence[str], settings: Settings
) -> dict[str, DerivedValues]:
    """Compute the derived values of the given projects and services."""
    params = load_parameters(settings.codebook_path).period
    modification_types = modification_event_types(session)
    focal_id = focal_org_id(session, settings)
    result: dict[str, DerivedValues] = {}
    for start in range(0, len(entity_ids), _BATCH):
        chunk = list(entity_ids[start : start + _BATCH])
        events = _load_events(session, chunk)
        participations = _load_participations(session, chunk, focal_id)
        for entity_id in chunk:
            result[entity_id] = compute_derived(
                events.get(entity_id, []),
                participations.get(entity_id, []),
                modification_types,
                params,
            )
    return result


def stored_rows(session: Session, entity_ids: Sequence[str]) -> dict[str, DerivedValues]:
    """The stored derived values of the given entities (missing rows are omitted)."""
    names = list(DerivedValues.__dataclass_fields__)
    stored: dict[str, DerivedValues] = {}
    for start in range(0, len(entity_ids), _BATCH):
        chunk = list(entity_ids[start : start + _BATCH])
        for row in session.scalars(select(Derived).where(Derived.entity_id.in_(chunk))):
            values = {name: getattr(row, name) for name in names}
            values["existed_before_invasion"] = bool(values["existed_before_invasion"])
            stored[row.entity_id] = DerivedValues(**values)
    return stored


def recompute(session: Session, entity_ids: Iterable[str], at: str, settings: Settings) -> int:
    """Recompute the rows of the given projects and services (other IDs are ignored).

    Missing rows are inserted; rows are only updated when a value changes. Returns the
    number of rows written.
    """
    ids = sorted({i for i in entity_ids if i and type_of_id(i) in DERIVED_TYPES})
    if not ids:
        return 0
    computed = compute_for(session, ids, settings)
    stored = stored_rows(session, ids)
    written = 0
    for entity_id in ids:
        values = computed[entity_id]
        if stored.get(entity_id) == values:
            continue
        row = {"entity_id": entity_id, **values.as_row(), "computed_at": at}
        statement = sqlite_insert(Derived).values(**row)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[Derived.entity_id],
                set_={key: statement.excluded[key] for key in row if key != "entity_id"},
            )
        )
        written += 1
    return written


def all_entity_ids(session: Session) -> list[str]:
    """IDs of every project and service, deleted or not."""
    projects = session.execute(select(Project.id)).scalars().all()
    services = session.execute(select(Service.id)).scalars().all()
    return [*projects, *services]


def recompute_all(session: Session, at: str, settings: Settings) -> int:
    """Recompute every row (``mdt recompute``) and store the inputs hash."""
    written = recompute(session, all_entity_ids(session), at, settings)
    store_inputs_hash(session, inputs_hash(session, settings))
    return written


def inputs_hash(session: Session, settings: Settings) -> str:
    """Hash of everything a full recompute depends on (§8.1): parameters.yaml, the focal
    organisation's ID and the set of modification event types."""
    payload = {
        "parameters": parameters_digest(settings.codebook_path),
        "focal_org_id": focal_org_id(session, settings),
        "modification_types": modification_event_types(session),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def stored_inputs_hash(session: Session) -> str | None:
    """The inputs hash of the last full recompute."""
    return session.execute(select(AppState.value).where(AppState.key == HASH_KEY)).scalar()


def store_inputs_hash(session: Session, value: str) -> None:
    """Remember the inputs hash in ``app_state``."""
    statement = sqlite_insert(AppState).values(key=HASH_KEY, value=value)
    session.execute(
        statement.on_conflict_do_update(index_elements=[AppState.key], set_={"value": value})
    )


def ensure_current(session: Session, at: str, settings: Settings) -> bool:
    """Run a full recompute if the inputs hash changed; returns True if it ran."""
    if stored_inputs_hash(session) == inputs_hash(session, settings):
        return False
    recompute_all(session, at, settings)
    return True
