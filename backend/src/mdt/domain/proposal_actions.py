"""Decisions on proposals (docs/DATA_MODEL.md §16.2, §16.4; docs/API.md §7.4).

* **Accept** re-checks the proposal inside one write unit and writes through the write
  machinery with ``Actor.accept``: channel ``ui``, author ``user``, ``revision.proposal_id``.
  Values observed in a source and taken unchanged keep the collector as ``src`` and their
  snapshots; edited values, add-only list results, the person's additions and suggested
  interpretations are ``manual``. A proposal with nothing left to write is superseded.
* **Edit & accept** passes ``values`` (state ``accepted_modified`` when they change what was
  proposed); **link to existing** binds a ``create_entity`` proposal's observation to a
  record; **reject** needs a note and writes no curated data.
* **Bulk** decisions run one write unit per proposal; a bulk accept leaves proposals that
  need values and stale ``update_field`` proposals open.
* A ``possible_duplicate`` of projects or services is accepted by merging them
  (:func:`mdt.domain.merge.merge`).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy import Table, select, update
from sqlalchemy.orm import Session

from mdt.db.models import Project, Proposal, SourceObservation
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import USER_NAME, Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import (
    DomainError,
    EntityDeletedError,
    InvalidStateError,
    NotFoundError,
    Problems,
    ValidationError,
)
from mdt.domain.ids import new_batch_id
from mdt.domain.merge import merge
from mdt.domain.normalize import normalize_value, values_equal
from mdt.domain.observations import bind_observation, resolve_subject
from mdt.domain.proposals import SYSTEM
from mdt.domain.reconcile import ADD_ONLY_URL_LISTS, urls_to_add
from mdt.domain.records import Row, load_links, load_row, stored_values
from mdt.domain.registry import ENTITY_TYPES, EVIDENCE, EntityTypeSpec, type_of_id
from mdt.domain.writes import (
    WriteUnit,
    clean_note,
    create_record,
    normalize_changes,
    update_record,
)

MAX_BULK: Final = 500
BULK_ACTIONS: Final = ("accept", "reject")
#: The evidence values a ``create_event`` proposal carries (DATA_MODEL §16.1).
EVIDENCE_KEYS: Final = (
    "document_id",
    "text_hash",
    "char_start",
    "char_end",
    "url",
    "archive_url",
    "raw_snapshot_id",
    "retrieved_at",
)
_SLUG_INVALID = re.compile(r"[^a-z0-9-]")
_SLUG_DASHES = re.compile(r"-{2,}")
_SLUG_MAX = 90


def _table() -> Table:
    table = Proposal.__table__
    assert isinstance(table, Table)
    return table


@dataclass(frozen=True)
class Decision:
    """Outcome of accepting one proposal."""

    proposal_id: str
    changed: bool
    result_id: str | None
    revision_ids: list[int] = field(default_factory=list)
    batch_id: str | None = None


class _SubjectDeleted(Exception):
    """The subject turned out deleted: the proposal is superseded, the request refused."""

    def __init__(self, row: Row) -> None:
        super().__init__(row["id"])
        self.row = row


@dataclass
class _Accept:
    """The write context of one acceptance."""

    session: Session
    proposal: Row
    values: Mapping[str, Any] | None
    match_id: str | None
    note: str | None
    batch_id: str | None
    now: str
    revision_ids: list[int] = field(default_factory=list)

    @property
    def actor(self) -> Actor:
        """``Actor.accept`` with the proposal's source as ``src`` of observed values."""
        source = f"collector:{self.proposal['collector']}@{self.proposal['last_run_id']}"
        return Actor.accept(self.proposal["id"], source)

    @property
    def revision_note(self) -> str:
        """The decision note, else ``Accepted proposal <id>``."""
        return self.note or f"Accepted proposal {self.proposal['id']}"

    def unit(self, spec: EntityTypeSpec) -> WriteUnit:
        """A write unit context for ``spec`` with the accepting actor."""
        return WriteUnit.open(self.session, spec, self.actor)

    def record(self, revision_id: int | None) -> None:
        """Keep the ID of a revision this acceptance wrote."""
        if revision_id is not None:
            self.revision_ids.append(revision_id)


# --------------------------------------------------------------------------------------
# Loading and closing
# --------------------------------------------------------------------------------------


def load_proposal(session: Session, proposal_id: str) -> Row:
    """The proposal row (404 if unknown), inside the caller's transaction."""
    table = _table()
    row = session.execute(select(table).where(table.c.id == proposal_id)).mappings().first()
    if row is None:
        raise NotFoundError("No such proposal")
    return dict(row)


def _require_open(row: Row) -> None:
    if row["state"] != "open":
        raise InvalidStateError(str(row["state"]), "The proposal is not open")


def _close(
    session: Session,
    proposal_id: str,
    state: str,
    now: str,
    *,
    by: str = USER_NAME,
    note: str | None = None,
    result_id: str | None = None,
) -> None:
    table = _table()
    session.execute(
        update(table)
        .where(table.c.id == proposal_id)
        .values(state=state, decided_at=now, decided_by=by, decision_note=note, result_id=result_id)
    )


def _nothing_left(ctx: _Accept, reason: str) -> Decision:
    """Nothing is left to write: the proposal becomes superseded (``changed: false``)."""
    _close(ctx.session, ctx.proposal["id"], "superseded", ctx.now, by=SYSTEM, note=reason)
    return Decision(ctx.proposal["id"], False, None, [], ctx.batch_id)


def _live_subject(ctx: _Accept, record_id: str | None = None) -> tuple[EntityTypeSpec, Row]:
    """The proposal's subject (or ``record_id``) if it is live; a deleted one supersedes
    the proposal and refuses the acceptance (``409 entity_deleted``)."""
    subject_id = record_id or ctx.proposal["subject_id"]
    entity_type = type_of_id(subject_id or "")
    row = load_row(ctx.session, ENTITY_TYPES[entity_type], subject_id) if entity_type else None
    if row is None:
        raise NotFoundError("The proposal's record does not exist")
    if row["deleted_at"] is not None:
        _close(
            ctx.session,
            ctx.proposal["id"],
            "superseded",
            ctx.now,
            by=SYSTEM,
            note="The subject was deleted",
        )
        raise _SubjectDeleted(row)
    return ENTITY_TYPES[str(entity_type)], row


def _prefixed(error: ValidationError, keys: Sequence[str]) -> ValidationError:
    """The error with the paths of the person's ``values`` written as ``values.<field>``."""
    details = {
        (f"values.{path}" if path.split("[")[0].split(".")[0] in keys else path): messages
        for path, messages in (error.details or {}).items()
    }
    return ValidationError(details, error.message)


def _check_keys(values: Mapping[str, Any], allowed: Collection[str]) -> None:
    problems = Problems()
    for name in values:
        if name not in allowed:
            problems.add(f"values.{name}", "cannot be set when accepting this proposal")
    problems.raise_if_any()


# --------------------------------------------------------------------------------------
# Accept
# --------------------------------------------------------------------------------------


def accept_proposal(
    session: Session,
    proposal_id: str,
    *,
    values: Mapping[str, Any] | None = None,
    match_id: str | None = None,
    note: str | None = None,
    batch_id: str | None = None,
) -> Decision:
    """Accept a proposal, with ``values`` (edit & accept) or ``match_id`` (link to an
    existing record, ``create_entity`` only); ``batch_id`` groups the revisions of a bulk
    accept. Errors: ``409 invalid_state`` (not open), ``409 entity_deleted``, ``400
    validation_error``, and the merge's errors for duplicates of projects and services."""
    clean = clean_note(note)
    if values is not None and not isinstance(values, Mapping):
        raise ValidationError.single("values", "must be an object")
    with read_transaction(session):
        proposal = load_proposal(session, proposal_id)
    if match_id is not None and proposal["kind"] != "create_entity":
        raise ValidationError.single("match_id", "Only a new record can be linked to another")
    if proposal["kind"] == "possible_duplicate" and proposal["entity_type"] in (
        "project",
        "service",
    ):
        return _accept_merge(session, proposal, values, clean)
    deleted: Row | None = None
    decision: Decision | None = None
    with write_transaction(session):
        proposal = load_proposal(session, proposal_id)
        _require_open(proposal)
        ctx = _Accept(
            session, proposal, values, match_id, clean, batch_id or new_batch_id(), utc_now()
        )
        try:
            decision = _ACCEPT[proposal["kind"]](ctx)
        except _SubjectDeleted as exc:  # checked before any write: commit the supersede
            deleted = exc.row
    if deleted is not None:
        raise EntityDeletedError(deleted["deleted_at"], deleted["deleted_by"])
    assert decision is not None
    return decision


def _accept_update_field(ctx: _Accept) -> Decision:
    """Write the proposed (or edited) value of one field; text versions as a unit."""
    spec, subject = _live_subject(ctx)
    name = str(ctx.proposal["field"])
    if name == "text_hash" and spec.name == "document":
        return _accept_text_version(ctx, subject)
    field_spec = spec.field(name)
    links = load_links(ctx.session, [subject["id"]])[subject["id"]] if name == "links" else None
    current = stored_values(spec, subject, links)[name]
    proposed = ctx.proposal["proposed_value"]
    add_only = name in ADD_ONLY_URL_LISTS
    # Accepted as proposed: an add-only list gets the proposal's URLs appended to the
    # current list (a manual result), any other value is the observed one.
    plain = [*current, *urls_to_add(current, proposed)] if add_only else proposed
    value = plain
    if ctx.values is not None:
        _check_keys(ctx.values, (name,))
        if field_spec.system:
            raise ValidationError.single(f"values.{name}", "is set by the system")
        problems = Problems()
        value = normalize_value(field_spec, ctx.values.get(name), problems, f"values.{name}")
        problems.raise_if_any()
    edited = not values_equal(field_spec, value, plain)
    if values_equal(field_spec, current, value):
        return _nothing_left(ctx, "The field already holds this value")
    observed = not edited and not add_only
    snapshots = (ctx.proposal["payload"] or {}).get("field_snapshots") or {}
    field_snapshots = (
        {name: list(snapshots.get(name) or [ctx.proposal["raw_snapshot_id"]])} if observed else None
    )
    unit = ctx.unit(spec)
    try:
        provided = normalize_changes(unit, {name: value}, creating=False, allow_system=observed)
        result = update_record(
            unit,
            subject,
            provided,
            note=ctx.revision_note,
            batch_id=ctx.batch_id,
            field_snapshots=field_snapshots,
        )
    except ValidationError as exc:
        raise (_prefixed(exc, [name]) if ctx.values is not None else exc) from exc
    ctx.record(result.revision_id)
    state = "accepted_modified" if edited else "accepted"
    _close(ctx.session, ctx.proposal["id"], state, ctx.now, note=ctx.note, result_id=subject["id"])
    return Decision(ctx.proposal["id"], True, subject["id"], ctx.revision_ids, ctx.batch_id)


def _accept_text_version(ctx: _Accept, subject: Row) -> Decision:
    """A text version is written as a unit by the domain layer (§15.6, §16.4)."""
    if ctx.values is not None:
        raise ValidationError.single("values", "A text version is accepted or rejected as it is")
    spec = ENTITY_TYPES["document"]
    proposed = ctx.proposal["proposed_value"]
    if subject["text_hash"] == proposed:
        return _nothing_left(ctx, "The document already has this text version")
    payload = ctx.proposal["payload"] or {}
    changes = {
        "text_hash": proposed,
        "raw_snapshot_id": payload.get("raw_snapshot_id"),
        "retrieved_at": payload.get("retrieved_at"),
        "extraction_method": payload.get("extraction_method"),
    }
    snapshot = [payload.get("raw_snapshot_id") or ctx.proposal["raw_snapshot_id"]]
    unit = ctx.unit(spec)
    provided = normalize_changes(unit, changes, creating=False, allow_system=True)
    result = update_record(
        unit,
        subject,
        provided,
        note=ctx.revision_note,
        batch_id=ctx.batch_id,
        field_snapshots=dict.fromkeys(changes, snapshot),
    )
    ctx.record(result.revision_id)
    _close(
        ctx.session, ctx.proposal["id"], "accepted", ctx.now, note=ctx.note, result_id=subject["id"]
    )
    return Decision(ctx.proposal["id"], True, subject["id"], ctx.revision_ids, ctx.batch_id)


def _accept_discontinued(ctx: _Accept) -> Decision:
    """Set the proposed (or chosen) status."""
    spec, subject = _live_subject(ctx)
    proposed = (ctx.proposal["proposed_value"] or {}).get("status")
    status = proposed
    if ctx.values is not None:
        _check_keys(ctx.values, ("status",))
        status = ctx.values.get("status")
    field_spec = spec.field("status")
    if values_equal(field_spec, stored_values(spec, subject)["status"], status):
        return _nothing_left(ctx, "The record already has this status")
    unit = ctx.unit(spec)
    edited = not values_equal(field_spec, status, proposed)
    try:
        provided = normalize_changes(unit, {"status": status}, creating=False)
        result = update_record(
            unit, subject, provided, note=ctx.revision_note, batch_id=ctx.batch_id
        )
    except ValidationError as exc:
        raise (_prefixed(exc, ["status"]) if ctx.values is not None else exc) from exc
    ctx.record(result.revision_id)
    state = "accepted_modified" if edited else "accepted"
    _close(ctx.session, ctx.proposal["id"], state, ctx.now, note=ctx.note, result_id=subject["id"])
    return Decision(ctx.proposal["id"], True, subject["id"], ctx.revision_ids, ctx.batch_id)


def generate_slug(session: Session, site_slug: str | None) -> str:
    """A project slug from the source's slug (DATA_MODEL §16.1): lower-cased, ``_`` → ``-``,
    other characters outside ``[a-z0-9-]`` removed, suffixed ``-2``, ``-3`` … while taken
    (deleted projects included)."""
    base = _SLUG_INVALID.sub("", (site_slug or "").lower().replace("_", "-"))
    base = _SLUG_DASHES.sub("-", base).strip("-")[:_SLUG_MAX].strip("-") or "project"
    taken = set(
        session.execute(select(Project.slug).where(Project.slug.like(f"{base}%"))).scalars()
    )
    slug, suffix = base, 2
    while slug in taken:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


def _accept_create_entity(ctx: _Accept) -> Decision:
    """Create the record from the observed fields and the person's values, or link."""
    proposal = ctx.proposal
    spec = ENTITY_TYPES[proposal["entity_type"]]
    observation = _observation(ctx)
    if observation is not None and observation["subject_id"]:
        resolved = resolve_subject(ctx.session, observation["subject_id"])
        if resolved is not None and resolved[1]["deleted_at"] is None:
            return _nothing_left(ctx, f"The source entry is already bound to {resolved[0]}")
    if ctx.match_id is not None:
        return _link_existing(ctx, spec, observation)
    payload = proposal["payload"] or {}
    observed: dict[str, Any] = dict(payload.get("fields") or {})
    person = dict(ctx.values or {})
    _check_keys(person, [field_spec.name for field_spec in spec.fields if field_spec.in_create])
    if spec.name == "project":
        problems = Problems()
        for name in ("in_paper_scope", "scope_note"):
            if person.get(name) in (None, ""):
                problems.add(f"values.{name}", "is required to create a project")
        problems.raise_if_any()
        if not person.get("slug"):
            person["slug"] = generate_slug(ctx.session, payload.get("site_slug"))
    unit = ctx.unit(spec)
    try:
        provided = normalize_changes(unit, {**observed, **person}, creating=True, allow_system=True)
    except ValidationError as exc:
        raise _prefixed(exc, list(person)) from exc
    # Observed values the person did not change keep the collector as their source.
    changed = {
        name
        for name in person
        if name in observed
        and not values_equal(spec.field(name), observed[name], provided.get(name))
    }
    taken = [
        name
        for name in observed
        if name in provided and (name not in person or name not in changed)
    ]
    snapshots = payload.get("field_snapshots") or {}
    try:
        result = create_record(
            unit,
            provided,
            note=ctx.revision_note,
            batch_id=ctx.batch_id,
            field_snapshots={
                name: list(snapshots.get(name) or [proposal["raw_snapshot_id"]]) for name in taken
            },
        )
    except ValidationError as exc:
        raise _prefixed(exc, list(person)) from exc
    ctx.record(result.revision_id)
    if observation is not None:
        bind_observation(ctx.session, observation["id"], result.entity_id, "proposal", ctx.now)
    state = "accepted_modified" if changed else "accepted"
    _close(ctx.session, proposal["id"], state, ctx.now, note=ctx.note, result_id=result.entity_id)
    return Decision(proposal["id"], True, result.entity_id, ctx.revision_ids, ctx.batch_id)


def _observation(ctx: _Accept) -> Row | None:
    observation_id = ctx.proposal["observation_id"]
    if observation_id is None:
        return None
    table = SourceObservation.__table__
    assert isinstance(table, Table)
    row = ctx.session.execute(select(table).where(table.c.id == observation_id)).mappings().first()
    return dict(row) if row is not None else None


def _link_existing(ctx: _Accept, spec: EntityTypeSpec, observation: Row | None) -> Decision:
    """Link to existing: bind the observation to a live record of the type, nothing else."""
    match_id = str(ctx.match_id)
    row = load_row(ctx.session, spec, match_id) if type_of_id(match_id) == spec.name else None
    if row is None:
        raise ValidationError.single("match_id", f"must be an existing {spec.label.lower()}")
    if row["deleted_at"] is not None:
        raise EntityDeletedError(row["deleted_at"], row["deleted_by"])
    if observation is not None:
        bind_observation(ctx.session, observation["id"], match_id, "proposal", ctx.now)
    _close(
        ctx.session,
        ctx.proposal["id"],
        "accepted_modified",
        ctx.now,
        note=ctx.note,
        result_id=match_id,
    )
    return Decision(ctx.proposal["id"], True, match_id, [], ctx.batch_id)


def _accept_create_event(ctx: _Accept) -> Decision:
    """Create the event and its evidence (two revisions, one batch)."""
    proposal = ctx.proposal
    payload = proposal["payload"] or {}
    proposed = {
        key: value for key, value in (payload.get("event") or {}).items() if value is not None
    }
    spec = ENTITY_TYPES["event"]
    allowed = [field_spec.name for field_spec in spec.fields if field_spec.in_create]
    person = dict(ctx.values or {})
    _check_keys(person, allowed)
    event = {**proposed, **person}
    _live_subject(ctx, str(event.get("subject_id") or proposal["subject_id"]))
    unit = ctx.unit(spec)
    try:
        provided = normalize_changes(unit, event, creating=True)
        created = create_record(unit, provided, note=ctx.revision_note, batch_id=ctx.batch_id)
    except ValidationError as exc:
        raise _prefixed(exc, list(person)) from exc
    ctx.record(created.revision_id)
    edited = any(
        not values_equal(spec.field(name), proposed.get(name), provided.get(name))
        for name in person
    )
    evidence_values = {
        key: value
        for key, value in (payload.get("evidence") or {}).items()
        if key in EVIDENCE_KEYS and value is not None
    }
    evidence = {
        "subject_id": created.entity_id,
        "target": "entity",
        **evidence_values,
        "quote": proposal["quote"],
    }
    evidence_unit = unit.for_type(EVIDENCE)
    result = create_record(
        evidence_unit,
        normalize_changes(evidence_unit, evidence, creating=True, allow_system=True),
        note=ctx.revision_note,
        batch_id=ctx.batch_id,
    )
    ctx.record(result.revision_id)
    state = "accepted_modified" if edited else "accepted"
    _close(ctx.session, proposal["id"], state, ctx.now, note=ctx.note, result_id=created.entity_id)
    return Decision(proposal["id"], True, created.entity_id, ctx.revision_ids, ctx.batch_id)


def _accept_document_duplicate(ctx: _Accept) -> Decision:
    """The chosen document is screened out as a duplicate of the other one."""
    proposal = ctx.proposal
    if ctx.values is None:
        raise ValidationError.single("values", "Choose the duplicate (values.duplicate_id)")
    _check_keys(ctx.values, ("duplicate_id",))
    pair = (proposal["subject_id"], proposal["related_id"])
    duplicate_id = ctx.values.get("duplicate_id")
    if duplicate_id not in pair:
        raise ValidationError.single("values.duplicate_id", "must be one of the two documents")
    other = pair[1] if duplicate_id == pair[0] else pair[0]
    _live_subject(ctx, other)
    spec, duplicate = _live_subject(ctx, str(duplicate_id))
    changes = {
        "screening_status": "excluded",
        "screening_reason": "duplicate",
        "screening_note": f"Duplicate of {other}",
    }
    current = stored_values(spec, duplicate)
    if all(values_equal(spec.field(name), current[name], value) for name, value in changes.items()):
        return _nothing_left(ctx, "The document is already marked as a duplicate of the other")
    unit = ctx.unit(spec)
    provided = normalize_changes(unit, changes, creating=False)
    result = update_record(unit, duplicate, provided, note=ctx.revision_note, batch_id=ctx.batch_id)
    ctx.record(result.revision_id)
    _close(
        ctx.session, proposal["id"], "accepted", ctx.now, note=ctx.note, result_id=str(duplicate_id)
    )
    return Decision(proposal["id"], True, str(duplicate_id), ctx.revision_ids, ctx.batch_id)


def _accept_merge(
    session: Session, proposal: Row, values: Mapping[str, Any] | None, note: str | None
) -> Decision:
    """A duplicate of projects or services is accepted by merging them (§18)."""
    _require_open(proposal)
    if values is None:
        raise ValidationError.single("values", "Choose the survivor (values.survivor_id)")
    _check_keys(values, ("survivor_id", "fields"))
    pair = (proposal["subject_id"], proposal["related_id"])
    survivor_id = values.get("survivor_id")
    if survivor_id not in pair:
        raise ValidationError.single("values.survivor_id", "must be one of the two records")
    merged_id = pair[1] if survivor_id == pair[0] else pair[0]
    choices = values.get("fields")
    if choices is not None and not isinstance(choices, Mapping):
        raise ValidationError.single("values.fields", "must be an object")
    result = merge(
        session,
        proposal["entity_type"],
        str(survivor_id),
        str(merged_id),
        choices,
        note,
        proposal_id=proposal["id"],
    )
    return Decision(proposal["id"], True, result.record_id, result.revision_ids, result.batch_id)


def _accept_duplicate(ctx: _Accept) -> Decision:
    """Documents only; projects and services are merged before the write unit."""
    if ctx.proposal["entity_type"] != "document":
        raise ValidationError.single("values", "Duplicates of this type are merged")
    return _accept_document_duplicate(ctx)


_ACCEPT = {
    "update_field": _accept_update_field,
    "possibly_discontinued": _accept_discontinued,
    "create_entity": _accept_create_entity,
    "create_event": _accept_create_event,
    "possible_duplicate": _accept_duplicate,
}


# --------------------------------------------------------------------------------------
# Reject
# --------------------------------------------------------------------------------------


def reject_proposal(session: Session, proposal_id: str, note: str | None) -> None:
    """Reject a proposal with a note (required, ≤ 2 000 characters); no curated data is
    written, and the same proposal is never raised again (rejection memory)."""
    clean = clean_note(note)
    if not clean:
        raise ValidationError.single("note", "A note is required to reject a proposal")
    with write_transaction(session):
        proposal = load_proposal(session, proposal_id)
        _require_open(proposal)
        _close(session, proposal_id, "rejected", utc_now(), note=clean)


# --------------------------------------------------------------------------------------
# Bulk
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BulkDecision:
    """Outcome of a bulk decision: per proposal ``accepted``, ``rejected``,
    ``superseded``, ``stale``, ``needs_values`` or ``error`` (API §7.4)."""

    batch_id: str
    results: list[dict[str, Any]]


def needs_values(proposal: Mapping[str, Any]) -> bool:
    """Proposals a bulk accept cannot decide: new projects (their scope is the person's
    decision) and possible duplicates (the person chooses)."""
    kind, entity_type = str(proposal["kind"]), str(proposal["entity_type"])
    return kind == "possible_duplicate" or (kind == "create_entity" and entity_type == "project")


def is_stale(session: Session, proposal: Mapping[str, Any]) -> bool:
    """An ``update_field`` proposal whose field changed after it was last raised."""
    if proposal["kind"] != "update_field" or proposal["subject_id"] is None:
        return False
    spec = ENTITY_TYPES[proposal["entity_type"]]
    row = load_row(session, spec, proposal["subject_id"])
    if row is None:
        return False
    name = str(proposal["field"])
    links = load_links(session, [row["id"]])[row["id"]] if name == "links" else None
    live = stored_values(spec, row, links)[name]
    return not values_equal(spec.field(name), live, proposal["current_value"])


def _check_bulk(ids: Sequence[Any], action: str, note: str | None) -> None:
    problems = Problems()
    if not isinstance(ids, list) or not ids:
        problems.add("ids", "must be a non-empty list")
    elif len(ids) > MAX_BULK:
        problems.add("ids", f"must have at most {MAX_BULK} items")
    else:
        seen: set[str] = set()
        for index, proposal_id in enumerate(ids):
            if not isinstance(proposal_id, str) or not proposal_id:
                problems.add(f"ids[{index}]", "must be a proposal ID")
            elif proposal_id in seen:
                problems.add(f"ids[{index}]", "is duplicated")
            else:
                seen.add(proposal_id)
    if action not in BULK_ACTIONS:
        problems.add("action", f"must be one of {', '.join(BULK_ACTIONS)}")
    if action == "reject" and not note:
        problems.add("note", "A note is required to reject proposals")
    problems.raise_if_any()


def bulk_decide(
    session: Session, ids: Sequence[str], action: str, note: str | None
) -> BulkDecision:
    """Accept or reject many proposals, each its own write unit; the revisions of a bulk
    accept share one ``batch_id``."""
    clean = clean_note(note)
    _check_bulk(ids, action, clean)
    batch_id = new_batch_id()
    results = []
    for proposal_id in ids:
        status, error = _bulk_item(session, proposal_id, action, clean, batch_id)
        results.append({"id": proposal_id, "status": status, "error": error})
    return BulkDecision(batch_id, results)


def _bulk_item(
    session: Session, proposal_id: str, action: str, note: str | None, batch_id: str
) -> tuple[str, dict[str, Any] | None]:
    try:
        if action == "reject":
            reject_proposal(session, proposal_id, note)
            return "rejected", None
        with read_transaction(session):
            proposal = load_proposal(session, proposal_id)
            _require_open(proposal)
            if needs_values(proposal):
                return "needs_values", None
            if is_stale(session, proposal):
                return "stale", None
        decision = accept_proposal(session, proposal_id, note=note, batch_id=batch_id)
        return ("accepted" if decision.changed else "superseded"), None
    except DomainError as exc:
        return "error", exc.to_dict()
