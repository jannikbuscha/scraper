"""Proposals of the review inbox, run side (docs/DATA_MODEL.md §14.6, §16.1-§16.3).

Runs raise proposals through :func:`raise_proposal`, which deduplicates them by
``dedup_key``: an open proposal with the same key is refreshed, a rejected one suppresses
the new one (rejection memory), an accepted one too unless the source changed and came back,
and otherwise a new row opens. The system supersedes open proposals whose situation no
longer applies (:func:`supersede`). After a run, :func:`detect_duplicates` raises the
``possible_duplicate`` proposals of the records the run created or whose text changed.

Every function here runs inside the caller's write unit except :func:`detect_duplicates`,
which is the run's finish step and opens its own.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import ColumnElement, Table, insert, select, update
from sqlalchemy.orm import Session

from mdt.collectors.duplicates import (
    DuplicatePair,
    find_document_duplicates,
    find_service_duplicates,
)
from mdt.db.models import Proposal
from mdt.db.session import write_transaction
from mdt.domain.clock import utc_now
from mdt.domain.ids import new_id
from mdt.domain.normalize import canonical_json
from mdt.domain.records import load_row
from mdt.domain.registry import ENTITY_TYPES, type_of_id
from mdt.domain.run_effects import RunEffects

if TYPE_CHECKING:
    from mdt.collectors.base import RunScope

KINDS: Final = (
    "create_entity",
    "update_field",
    "create_event",
    "possible_duplicate",
    "possibly_discontinued",
)
STATES: Final = ("open", "accepted", "accepted_modified", "rejected", "superseded")
#: Dedup scope of the kinds that any collector may raise (DATA_MODEL §16.3).
ANY_COLLECTOR: Final = "*"
_SHARED_KINDS: Final = frozenset({"create_event", "possible_duplicate"})
#: The collector name of proposals raised by the event patterns (DATA_MODEL §15.9).
TAGGER: Final = "tagger"
#: ``decided_by`` of proposals the system closes.
SYSTEM: Final = "system"
#: Key of the run memory where the reconciler records the records created or with a changed
#: text, by type, for the duplicate detection (docs/COLLECTORS.md §7.8).
DUPLICATE_CANDIDATES: Final = "mdt.duplicate_candidates"

RaisedAction = Literal["opened", "refreshed", "suppressed"]


def _proposal_table() -> Table:
    table = Proposal.__table__
    assert isinstance(table, Table)
    return table


@dataclass(frozen=True)
class ProposalDraft:
    """A proposal a run wants to raise (the columns of DATA_MODEL §14.6 it sets).

    ``target`` and ``core`` are the parts of the dedup key that depend on the kind
    (DATA_MODEL §16.3): the observation key or subject, and the kind's core value.
    """

    kind: str
    entity_type: str
    collector: str
    target: str
    core: Any
    subject_id: str | None = None
    related_id: str | None = None
    field: str | None = None
    current_value: Any = None
    proposed_value: Any = None
    payload: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    raw_snapshot_id: str | None = None
    source_url: str | None = None
    quote: str | None = None
    locator: str | None = None
    observation_id: int | None = None

    @property
    def scope(self) -> str:
        """``*`` for the kinds that any collector raises alike, else the collector."""
        return ANY_COLLECTOR if self.kind in _SHARED_KINDS else self.collector

    @property
    def dedup_key(self) -> str:
        """SHA-256 of ``[kind, scope, entity_type, target, core]`` (canonical JSON)."""
        text = canonical_json([self.kind, self.scope, self.entity_type, self.target, self.core])
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Raised:
    """What :func:`raise_proposal` did: ``opened`` a new row, ``refreshed`` the open one,
    or ``suppressed`` it (a decision on the same key forbids a new row)."""

    action: RaisedAction
    proposal_id: str | None = None


def raise_proposal(
    session: Session, draft: ProposalDraft, *, run_id: str, now: str, effects: RunEffects
) -> Raised:
    """Raise ``draft`` in run ``run_id`` with the deduplication of DATA_MODEL §16.3."""
    table = _proposal_table()
    key = draft.dedup_key
    rows = [
        dict(row)
        for row in session.execute(select(table).where(table.c.dedup_key == key)).mappings()
    ]
    current = next((row for row in rows if row["state"] == "open"), None)
    if current is not None:
        _refresh(session, current, draft, run_id=run_id, now=now, effects=effects)
        return Raised("refreshed", current["id"])
    if _suppressed(session, draft, rows):
        return Raised("suppressed")
    proposal_id = new_id("prp")
    if draft.kind == "update_field":
        _supersede_older_values(session, draft, proposal_id, now, effects)
    session.execute(
        insert(table).values(
            id=proposal_id,
            kind=draft.kind,
            state="open",
            entity_type=draft.entity_type,
            subject_id=draft.subject_id,
            related_id=draft.related_id,
            field=draft.field,
            current_value=draft.current_value,
            proposed_value=draft.proposed_value,
            payload=dict(draft.payload),
            collector=draft.collector,
            first_run_id=run_id,
            last_run_id=run_id,
            raw_snapshot_id=draft.raw_snapshot_id,
            source_url=draft.source_url,
            quote=draft.quote,
            locator=draft.locator,
            observation_id=draft.observation_id,
            dedup_key=key,
            seen_count=1,
            created_at=now,
            last_seen_at=now,
        )
    )
    effects.count("proposals_opened")
    return Raised("opened", proposal_id)


def _refresh(
    session: Session,
    row: Mapping[str, Any],
    draft: ProposalDraft,
    *,
    run_id: str,
    now: str,
    effects: RunEffects,
) -> None:
    """Refresh an open proposal: bookkeeping and the latest source values, never its state.
    A run that raises it again counts once."""
    again = row["last_run_id"] != run_id
    table = _proposal_table()
    session.execute(
        update(table)
        .where(table.c.id == row["id"])
        .values(
            last_run_id=run_id,
            last_seen_at=now,
            seen_count=row["seen_count"] + (1 if again else 0),
            raw_snapshot_id=draft.raw_snapshot_id,
            source_url=draft.source_url,
            quote=draft.quote,
            locator=draft.locator,
            current_value=draft.current_value,
            payload=dict(draft.payload),
        )
    )
    if again:
        effects.count("proposals_seen_again")


def _suppressed(session: Session, draft: ProposalDraft, rows: Sequence[Mapping[str, Any]]) -> bool:
    """A rejected proposal with the key suppresses a new one for good; an accepted one does
    too, unless (``update_field``) a newer proposal of the same collector for the same
    subject and field was created after that decision: the source changed and came back."""
    if any(row["state"] == "rejected" for row in rows):
        return True
    accepted = [row for row in rows if row["state"] in ("accepted", "accepted_modified")]
    if not accepted:
        return False
    if draft.kind != "update_field":
        return True
    decided = max(str(row["decided_at"]) for row in accepted)
    table = _proposal_table()
    newer = session.execute(
        select(table.c.id)
        .where(
            table.c.kind == "update_field",
            table.c.collector == draft.collector,
            table.c.subject_id == draft.subject_id,
            table.c.field == draft.field,
            table.c.created_at > decided,
        )
        .limit(1)
    ).first()
    return newer is None


def _supersede_older_values(
    session: Session, draft: ProposalDraft, new_id_: str, now: str, effects: RunEffects
) -> None:
    """A newer ``update_field`` value of the same collector supersedes the open proposals
    for the same subject and field."""
    table = _proposal_table()
    supersede_where(
        session,
        [
            table.c.kind == "update_field",
            table.c.collector == draft.collector,
            table.c.subject_id == draft.subject_id,
            table.c.field == draft.field,
        ],
        f"Superseded by a newer value from the source (proposal {new_id_})",
        now=now,
        effects=effects,
    )


def supersede_where(
    session: Session,
    conditions: Sequence[ColumnElement[bool]],
    reason: str,
    *,
    now: str,
    effects: RunEffects | None = None,
    keep: Iterable[str] = (),
) -> list[str]:
    """Close the open proposals matching ``conditions`` as ``superseded`` (by the system,
    ``decision_note`` = ``reason``), except the IDs in ``keep``; returns their IDs."""
    table = _proposal_table()
    kept = list(keep)
    statement = select(table.c.id).where(table.c.state == "open", *conditions)
    if kept:
        statement = statement.where(table.c.id.not_in(kept))
    ids = [str(proposal_id) for proposal_id in session.execute(statement).scalars()]
    if ids:
        session.execute(
            update(table)
            .where(table.c.id.in_(ids))
            .values(state="superseded", decided_at=now, decided_by=SYSTEM, decision_note=reason)
        )
        if effects is not None:
            effects.count("proposals_superseded", len(ids))
    return ids


def supersede_for_subject(
    session: Session,
    subject_id: str,
    reason: str,
    *,
    now: str,
    effects: RunEffects | None = None,
    keep: Iterable[str] = (),
) -> list[str]:
    """Supersede every open proposal whose ``subject_id`` or ``related_id`` is the record
    (a deleted or merged subject, DATA_MODEL §16.3, §18)."""
    table = _proposal_table()
    return supersede_where(
        session,
        [(table.c.subject_id == subject_id) | (table.c.related_id == subject_id)],
        reason,
        now=now,
        effects=effects,
        keep=keep,
    )


def supersede_agreeing(
    session: Session,
    *,
    collector: str,
    subject_id: str,
    field_name: str,
    run_id: str,
    now: str,
    effects: RunEffects,
    keep: Iterable[str] = (),
) -> list[str]:
    """The source agrees with the current value again: supersede the collector's open
    ``update_field`` proposals for the subject and field (DATA_MODEL §15.5)."""
    table = _proposal_table()
    return supersede_where(
        session,
        [
            table.c.kind == "update_field",
            table.c.collector == collector,
            table.c.subject_id == subject_id,
            table.c.field == field_name,
        ],
        f"The source agrees with the current value (run {run_id})",
        now=now,
        effects=effects,
        keep=keep,
    )


# --------------------------------------------------------------------------------------
# Duplicate detection (docs/COLLECTORS.md §7.8)
# --------------------------------------------------------------------------------------


def duplicate_candidates(scope: RunScope) -> dict[str, set[str]]:
    """The run memory of records created or with a changed text, by type."""
    memory = scope.memory.setdefault(DUPLICATE_CANDIDATES, {})
    assert isinstance(memory, dict)
    return memory


def detect_duplicates(session: Session, scope: RunScope) -> None:
    """After the run's last candidate: the duplicate detection of docs/COLLECTORS.md §7.8
    over the documents and services the run created or whose text changed (as the
    reconciler recorded them in ``scope.memory``), raising one ``possible_duplicate``
    proposal per pair (DATA_MODEL §16.1, §16.3)."""
    candidates = duplicate_candidates(scope)
    documents = sorted(candidates.get("document", ()))
    services = sorted(candidates.get("service", ()))
    if not documents and not services:
        return
    effects = RunEffects()
    with write_transaction(session):
        now = utc_now()
        pairs = [
            *(find_document_duplicates(session, documents) if documents else ()),
            *(find_service_duplicates(session, services) if services else ()),
        ]
        for pair in pairs:
            raise_duplicate(
                session,
                pair,
                collector=scope.collector,
                run_id=scope.run_id,
                now=now,
                effects=effects,
            )
    effects.report(scope)


def raise_duplicate(
    session: Session,
    pair: DuplicatePair,
    *,
    collector: str,
    run_id: str,
    now: str,
    effects: RunEffects,
) -> Raised | None:
    """Raise the ``possible_duplicate`` proposal of one pair of live records of one type
    (``subject_id`` < ``related_id``); None if the pair does not qualify."""
    subject_id, related_id = sorted((pair.subject_id, pair.related_id))
    entity_type = type_of_id(subject_id)
    if subject_id == related_id or entity_type is None or entity_type != type_of_id(related_id):
        return None
    spec = ENTITY_TYPES[entity_type]
    for record_id in (subject_id, related_id):
        row = load_row(session, spec, record_id)
        if row is None or row["deleted_at"] is not None:
            return None
    draft = ProposalDraft(
        kind="possible_duplicate",
        entity_type=entity_type,
        collector=collector,
        target=subject_id,
        core=related_id,
        subject_id=subject_id,
        related_id=related_id,
        payload={"basis": pair.basis, "similarity": pair.similarity, "details": dict(pair.details)},
    )
    return raise_proposal(session, draft, run_id=run_id, now=now, effects=effects)
