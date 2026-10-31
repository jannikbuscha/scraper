"""Reconciliation of collector candidates (docs/DATA_MODEL.md §15).

The run framework (:mod:`mdt.collectors.run_context`) calls :func:`reconcile_candidate` for
``ctx.reconcile`` and :func:`record_first_archived` for ``ctx.first_archived``. Each call is
one write unit (§15.11) that re-reads the record and its ``field_meta``, decides and writes:

1. **Match** (§15.3): the observation's binding (merged records lead to their survivor),
   else the collector's match rules (``external_id``, ``document``, ``url_fields``). A
   deleted match blocks the candidate; several live matches bind nothing.
2. **New records** (§15.4): a direct create on channel ``collector`` where the collector
   declares ``creates``, else a ``create_entity`` proposal.
3. **Updates** (§15.5): per written field, an empty value changes nothing, an equal value
   supersedes the collector's open proposals for the field, a differing value is written
   when the field is unlocked and proposed when it is locked; URL lists are add-only;
   propose-only fields are always proposed. All writes of a candidate are one revision.
4. **Documents** (§15.6-§15.9, :mod:`mdt.domain.document_versions`): the text version as one
   unit, suggested links and event proposals.
5. The observation is upserted in the same unit; counters and messages reach the run only
   after the unit committed.

Within a run, each record is reconciled from its first candidate (§15.6); a later candidate
of the same record only updates its own observation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlsplit

from sqlalchemy import Table, or_, select
from sqlalchemy.orm import Session

from mdt.collectors.base import MATCH_RULES, MAX_QUOTE_CHARS, Candidate, Capture, Outcome
from mdt.collectors.duplicates import DuplicatePair
from mdt.collectors.parsing.dates import kyiv_date_of_wayback_timestamp
from mdt.db.models import Document, Event, Proposal, SourceObservation
from mdt.db.session import write_transaction
from mdt.domain import document_versions as docs
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import DomainError, Problems
from mdt.domain.ids import new_batch_id
from mdt.domain.normalize import INVALID, is_empty, normalize_value, values_equal
from mdt.domain.observations import (
    SeenObservation,
    bind_observation,
    note_seen,
    resolve_subject,
    upsert_observation,
)
from mdt.domain.proposals import (
    ProposalDraft,
    duplicate_candidates,
    raise_duplicate,
    raise_proposal,
    supersede_agreeing,
    supersede_for_subject,
    supersede_where,
)
from mdt.domain.records import Row, field_meta_of, load_links, stored_values, table_of
from mdt.domain.registry import ENTITY_TYPES, EVENT, EVIDENCE, EntityTypeSpec
from mdt.domain.run_effects import RunEffects
from mdt.domain.urls import UrlError, canonical_url
from mdt.domain.writes import WriteUnit, create_record, normalize_changes, update_record

if TYPE_CHECKING:
    from mdt.collectors.base import RunScope, TypeDeclaration

#: Fields that collectors set only when they create a record (or propose it): they never
#: rename a project, move a service to another project or change a document's source.
CREATE_ONLY: Final[Mapping[str, frozenset[str]]] = {
    "project": frozenset({"name_en", "name_uk"}),
    "service": frozenset({"project_id"}),
    "document": frozenset({"source_id", "external_id"}),
}
#: URL lists that collectors only extend, never shorten or reorder (§15.5).
ADD_ONLY_URL_LISTS: Final = frozenset({"ministry_urls", "official_urls", "urls", "archive_urls"})
#: The URL fields of the match rule ``url_fields`` (§15.3).
URL_MATCH_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "project": ("ministry_urls", "official_urls"),
    "service": ("urls",),
}
#: A person's judgement of the whole record locks every field for collectors (§15.5).
JUDGED: Final = frozenset({"verified", "disputed"})
#: Run memory: record ID → the key and values of the candidate it was reconciled from.
RECONCILED: Final = "mdt.reconciled"
#: Basis of the ``possible_duplicate`` proposals of a candidate with several live matches.
MATCH_BASIS: Final = "match"

MatchKind = Literal["bound", "blocked", "ambiguous", "none"]


# --------------------------------------------------------------------------------------
# Preparation (outside the write unit)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Prepared:
    """The candidate's observed values, normalised; invalid values are dropped."""

    fields: dict[str, Any]
    proposed: dict[str, Any]


def _prepare(
    candidate: Candidate, spec: EntityTypeSpec, declaration: TypeDeclaration, notices: RunEffects
) -> _Prepared:
    """Check the candidate against the declaration (a collector bug fails the run) and
    normalise its values (DATA_MODEL §1.2); a value that fails is dropped with the warning
    ``invalid_value`` (§15.1). Text-version values come from the candidate's text."""
    undeclared = sorted(set(candidate.fields) - declaration.writes) + sorted(
        set(candidate.proposed) - declaration.propose_only
    )
    unknown = sorted(
        name for name in {*candidate.fields, *candidate.proposed} if not spec.has_field(name)
    )
    if undeclared or unknown:
        raise ValueError(
            f"candidate {candidate.key}: fields outside the declaration or registry: "
            f"{', '.join(undeclared + unknown)}"
        )
    if "links" in candidate.fields:
        raise ValueError(f"candidate {candidate.key}: suggested links come from Candidate.links")

    def clean(values: Mapping[str, Any]) -> dict[str, Any]:
        """Normalise each value; drop invalid ones with a warning."""
        result: dict[str, Any] = {}
        for name, value in values.items():
            if name in docs.TEXT_VERSION_FIELDS and spec.name == "document":
                continue
            problems = Problems()
            normalized = normalize_value(spec.field(name), value, problems)
            if normalized is INVALID:
                notices.message(
                    "warning",
                    "invalid_value",
                    f"{candidate.key}: the value of {name} is not valid and was dropped",
                    url=candidate.url,
                    snapshot_id=candidate.evidence.raw_snapshot_id,
                    details={"key": candidate.key, "field": name},
                )
                continue
            result[name] = normalized
        return result

    return _Prepared(clean(candidate.fields), clean(candidate.proposed))


# --------------------------------------------------------------------------------------
# The write unit of one candidate
# --------------------------------------------------------------------------------------


@dataclass
class _Context:
    """Everything one candidate's write unit works with."""

    session: Session
    scope: RunScope
    candidate: Candidate
    declaration: TypeDeclaration
    spec: EntityTypeSpec
    prepared: _Prepared
    now: str
    effects: RunEffects
    unit: WriteUnit
    proposals: list[str] = field(default_factory=list)

    def propose(self, draft: ProposalDraft) -> bool:
        """Raise a proposal of this run; True if it is open now (opened or refreshed)."""
        raised = raise_proposal(
            self.session, draft, run_id=self.scope.run_id, now=self.now, effects=self.effects
        )
        if raised.proposal_id is not None:
            self.proposals.append(raised.proposal_id)
        return raised.proposal_id is not None

    def message(
        self, level: Literal["info", "warning"], code: str, text: str, **context: Any
    ) -> None:
        """A run message about this candidate."""
        self.effects.message(
            level,
            code,
            text,
            url=self.candidate.url,
            snapshot_id=self.candidate.evidence.raw_snapshot_id,
            **context,
        )


def reconcile_candidate(session: Session, scope: RunScope, candidate: Candidate) -> Outcome:
    """Reconcile one candidate as one write unit (DATA_MODEL §15.3-§15.11).

    Match it (binding, then the declared rules), create or update the record on channel
    ``collector`` for unlocked differences, raise proposals for locked and propose-only
    fields, add suggested links (running the tagger and the event patterns for a new or
    changed text, §15.8, §15.9) and upsert the candidate's observation. A candidate that
    fails validation at write time writes nothing but its observation (``write_error``).
    """
    declaration = scope.declaration[candidate.entity_type]
    spec = ENTITY_TYPES[candidate.entity_type]
    notices = RunEffects()
    prepared = _prepare(candidate, spec, declaration, notices)
    effects = RunEffects()
    try:
        with write_transaction(session):
            context = _Context(
                session=session,
                scope=scope,
                candidate=candidate,
                declaration=declaration,
                spec=spec,
                prepared=prepared,
                now=utc_now(),
                effects=effects,
                unit=WriteUnit.open(session, spec, Actor.collector(scope.collector, scope.run_id)),
            )
            outcome = _reconcile(context)
    except DomainError as exc:
        effects = RunEffects()
        _observe_after_error(session, scope, candidate, exc, effects)
        outcome = Outcome("observed")
    notices.report(scope)
    effects.report(scope)
    return outcome


def _see(
    session: Session, scope: RunScope, candidate: Candidate, now: str, effects: RunEffects
) -> SeenObservation:
    """Upsert the candidate's observation (§15.7)."""
    return upsert_observation(
        session,
        collector=scope.collector,
        run_id=scope.run_id,
        entity_type=candidate.entity_type,
        key=candidate.key,
        now=now,
        effects=effects,
        url=candidate.url,
        label=candidate.label,
        external_id=candidate.external_id,
        details=candidate.details,
        snapshot_id=candidate.evidence.raw_snapshot_id,
    )


def _observe_after_error(
    session: Session, scope: RunScope, candidate: Candidate, error: DomainError, effects: RunEffects
) -> None:
    """A candidate that failed at write time still counts as seen (§15.7)."""
    with write_transaction(session):
        now = utc_now()
        seen = _see(session, scope, candidate, now, effects)
        note_seen(
            session, seen, collector=scope.collector, run_id=scope.run_id, now=now, effects=effects
        )
    effects.message(
        "error",
        "write_error",
        f"{candidate.key}: {error.message}",
        url=candidate.url,
        snapshot_id=candidate.evidence.raw_snapshot_id,
        details={"key": candidate.key, "error": error.to_dict()},
    )


def _reconcile(ctx: _Context) -> Outcome:
    """Observe the key, match it and create, update, propose or block."""
    seen = _see(ctx.session, ctx.scope, ctx.candidate, ctx.now, ctx.effects)
    match = _match(ctx, seen)
    if match.kind == "blocked":
        assert match.record_id is not None
        return _blocked(ctx, match.record_id)
    if match.kind == "bound":
        assert match.record_id is not None and match.row is not None
        if match.newly_bound:
            _bind(ctx, seen, match.record_id)
        note_seen(
            ctx.session,
            seen,
            collector=ctx.scope.collector,
            run_id=ctx.scope.run_id,
            now=ctx.now,
            effects=ctx.effects,
        )
        if match.record_id in _reconciled(ctx.scope):
            return _again(ctx, match.record_id)
        return _update(ctx, match.record_id, match.row)
    if ctx.declaration.creates:
        return _create(ctx, seen, match)
    return _propose_create(ctx, seen, match.candidates)


# --------------------------------------------------------------------------------------
# Matching (§15.3)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Match:
    kind: MatchKind
    record_id: str | None = None
    row: Row | None = None
    candidates: tuple[str, ...] = ()
    newly_bound: bool = False
    rule: str | None = None


def _match(ctx: _Context, seen: SeenObservation) -> _Match:
    """The binding of the key, else the first declared rule that finds records."""
    if seen.subject_id is not None:
        resolved = resolve_subject(ctx.session, seen.subject_id)
        if resolved is None or resolved[1]["deleted_at"] is not None:
            return _Match("blocked", resolved[0] if resolved else seen.subject_id)
        return _Match("bound", resolved[0], resolved[1])
    for rule in MATCH_RULES:
        if rule not in ctx.declaration.match_rules:
            continue
        for ids in _rule_steps(ctx, rule, seen):
            found = _classify(ctx, ids, rule)
            if found is not None:
                return found
    return _Match("none")


def canonical_or_none(url: str | None) -> str | None:
    """The canonical form of a URL (DATA_MODEL §3.4), or None if it is empty or invalid."""
    if not url:
        return None
    try:
        return canonical_url(url)
    except UrlError:
        return None


def _rule_steps(ctx: _Context, rule: str, seen: SeenObservation) -> Iterator[list[str]]:
    """The records each step of a match rule finds, live and deleted (§15.3)."""
    candidate, session = ctx.candidate, ctx.session
    if rule == "external_id" and candidate.external_id:
        yield [
            str(subject_id)
            for subject_id in session.execute(
                select(SourceObservation.subject_id).where(
                    SourceObservation.collector == ctx.scope.collector,
                    SourceObservation.external_id == candidate.external_id,
                    SourceObservation.subject_id.is_not(None),
                    SourceObservation.id != seen.id,
                )
            ).scalars()
        ]
    elif rule == "document" and ctx.spec.name == "document":
        if candidate.external_id:
            yield _ids(
                session,
                select(Document.id).where(
                    Document.source_id == ctx.scope.collector,
                    Document.external_id == candidate.external_id,
                ),
            )
        url = canonical_or_none(ctx.prepared.fields.get("url") or candidate.url)
        if url:
            yield _ids(session, select(Document.id).where(Document.canonical_url == url))
    elif rule == "url_fields":
        url = canonical_or_none(candidate.url)
        if url:
            yield _url_field_matches(ctx, url)


def _ids(session: Session, statement: Any) -> list[str]:
    return [str(entity_id) for entity_id in session.execute(statement).scalars()]


def _url_field_matches(ctx: _Context, url: str) -> list[str]:
    """Records whose URL fields contain the canonical URL (live and deleted)."""
    columns = URL_MATCH_FIELDS.get(ctx.spec.name, ())
    if not columns:
        return []
    table = table_of(ctx.spec)
    found = []
    for row in ctx.session.execute(select(table.c.id, *(table.c[name] for name in columns))):
        urls = [value for name in columns for value in (getattr(row, name) or [])]
        if any(canonical_or_none(value) == url for value in urls):
            found.append(str(row.id))
    return found


def _classify(ctx: _Context, ids: Sequence[str], rule: str) -> _Match | None:
    """A unique live match binds; several live matches are ambiguous; only deleted
    matches block; nothing found lets the next rule try. Merged records count as their
    survivor."""
    resolved: dict[str, Row] = {}
    for record_id in ids:
        found = resolve_subject(ctx.session, record_id)
        if found is not None:
            resolved[found[0]] = found[1]
    if not resolved:
        return None
    live = sorted(record_id for record_id, row in resolved.items() if row["deleted_at"] is None)
    if len(live) == 1:
        return _Match("bound", live[0], resolved[live[0]], newly_bound=True, rule=rule)
    if live:
        return _Match("ambiguous", candidates=tuple(live), rule=rule)
    return _Match("blocked", sorted(resolved)[0], rule=rule)


def _bind(ctx: _Context, seen: SeenObservation, record_id: str) -> None:
    """Bind the key to the record it matched; an open ``create_entity`` proposal of the
    key no longer applies."""
    bind_observation(ctx.session, seen.id, record_id, "auto", ctx.now)
    proposal = Proposal.__table__
    assert isinstance(proposal, Table)
    supersede_where(
        ctx.session,
        [
            proposal.c.kind == "create_entity",
            proposal.c.collector == ctx.scope.collector,
            proposal.c.observation_id == seen.id,
        ],
        f"The source entry now matches {record_id}",
        now=ctx.now,
        effects=ctx.effects,
    )


def _blocked(ctx: _Context, record_id: str) -> Outcome:
    """A person deleted the record: nothing is written or proposed (§15.3), and its open
    proposals are superseded (§16.3)."""
    ctx.message(
        "info",
        "subject_deleted",
        f"{ctx.candidate.key}: the record {record_id} is deleted; nothing was written",
        subject_id=record_id,
        details={"key": ctx.candidate.key},
    )
    supersede_for_subject(
        ctx.session, record_id, "The subject was deleted", now=ctx.now, effects=ctx.effects
    )
    return Outcome("blocked", record_id)


# --------------------------------------------------------------------------------------
# One candidate per record and run (§15.6)
# --------------------------------------------------------------------------------------


def _reconciled(scope: RunScope) -> dict[str, dict[str, Any]]:
    """The run memory of reconciled records."""
    memory = scope.memory.setdefault(RECONCILED, {})
    assert isinstance(memory, dict)
    return memory


def _remember(ctx: _Context, record_id: str) -> None:
    """Record that this run reconciled ``record_id`` from this candidate."""
    _reconciled(ctx.scope)[record_id] = {
        "key": ctx.candidate.key,
        "fields": dict(ctx.prepared.fields),
        "proposed": dict(ctx.prepared.proposed),
    }


def _again(ctx: _Context, record_id: str) -> Outcome:
    """A later candidate of a record already reconciled in this run only updates its own
    observation; values that disagree with the first candidate are reported."""
    first = _reconciled(ctx.scope)[record_id]
    for section, values in (("fields", ctx.prepared.fields), ("proposed", ctx.prepared.proposed)):
        for name, value in sorted(values.items()):
            earlier = first[section]
            if name in earlier and not values_equal(ctx.spec.field(name), earlier[name], value):
                ctx.message(
                    "warning",
                    "conflicting_candidates",
                    f"{first['key']} and {ctx.candidate.key} disagree on {name} of {record_id}; "
                    f"the first candidate was used",
                    subject_id=record_id,
                    details={"keys": [first["key"], ctx.candidate.key], "field": name},
                )
    return Outcome("observed", record_id)


# --------------------------------------------------------------------------------------
# Unknown vocabulary codes (§15.10)
# --------------------------------------------------------------------------------------


def _known_codes(
    ctx: _Context, values: Mapping[str, Any], current: Mapping[str, Any] | None, record: str | None
) -> dict[str, Any]:
    """Drop codes that are not active terms of their vocabulary (a code already stored in
    the field may stay); each dropped code gets the warning ``unknown_code``."""
    result: dict[str, Any] = {}
    for name, value in values.items():
        spec = ctx.spec.field(name)
        if spec.type not in ("vocab", "vocab_list") or spec.vocabulary is None or value is None:
            result[name] = value
            continue
        stored = (current or {}).get(name)
        usable = {
            code for code, term in ctx.unit.terms.terms(spec.vocabulary).items() if term.active
        }
        usable |= set(stored) if isinstance(stored, list) else ({stored} if stored else set())
        codes = value if isinstance(value, list) else [value]
        for code in codes:
            if code not in usable:
                _unknown_code(ctx, name, spec.vocabulary, code, record)
        if isinstance(value, list):
            result[name] = [code for code in value if code in usable]
        elif value in usable:
            result[name] = value
    return result


def _unknown_code(ctx: _Context, name: str, vocabulary: str, code: str, record: str | None) -> None:
    labels = ctx.candidate.details.get("code_labels")
    label = labels.get(code) if isinstance(labels, Mapping) else None
    shown = f" (source label {label!r})" if label else ""
    ctx.message(
        "warning",
        "unknown_code",
        f"{ctx.candidate.key}: {code!r}{shown} is not an active code of the vocabulary "
        f"{vocabulary} ({name}); add the term so that a later run writes it",
        subject_id=record,
        details={
            "key": ctx.candidate.key,
            "field": name,
            "vocabulary": vocabulary,
            "code": code,
            "label": label,
        },
    )


# --------------------------------------------------------------------------------------
# Updates of a bound record (§15.5)
# --------------------------------------------------------------------------------------


@dataclass
class _Plan:
    """What one candidate does to its record: direct changes (with their snapshots),
    proposals, and fields where the source agrees with the current value."""

    changes: dict[str, Any] = field(default_factory=dict)
    snapshots: dict[str, list[str]] = field(default_factory=dict)
    drafts: list[ProposalDraft] = field(default_factory=list)
    agreeing: set[str] = field(default_factory=set)

    def write(self, name: str, value: Any, snapshots: Sequence[str]) -> None:
        """Write ``value`` directly, parsed from ``snapshots``."""
        self.changes[name] = value
        self.snapshots[name] = list(snapshots)


def urls_to_add(current: Sequence[str], observed: Sequence[str]) -> list[str]:
    """The observed URLs the list does not contain yet, compared by canonical URL."""
    present = {canonical_or_none(url) or url for url in current}
    added: list[str] = []
    for url in observed:
        key = canonical_or_none(url) or url
        if key not in present:
            present.add(key)
            added.append(url)
    return added


def _field_draft(
    ctx: _Context, record_id: str, name: str, current: Any, proposed: Any, *, add_only: bool
) -> ProposalDraft:
    """An ``update_field`` proposal (for add-only URL lists: the URLs to add)."""
    snapshots = ctx.candidate.snapshots_of(name)
    core = (
        [name, sorted(canonical_or_none(url) or url for url in proposed)]
        if add_only
        else [name, proposed]
    )
    evidence = ctx.candidate.evidence_of(name)
    return ProposalDraft(
        kind="update_field",
        entity_type=ctx.spec.name,
        collector=ctx.scope.collector,
        target=record_id,
        core=core,
        subject_id=record_id,
        field=name,
        current_value=current,
        proposed_value=proposed,
        payload={"field_snapshots": {name: snapshots}},
        raw_snapshot_id=snapshots[0],
        source_url=evidence.source_url,
        quote=evidence.quote,
        locator=evidence.locator,
    )


def _decide_write(
    ctx: _Context,
    plan: _Plan,
    record_id: str,
    name: str,
    value: Any,
    current: Mapping[str, Any],
    locked: bool,
) -> None:
    """One row of the decision table for a field the collector writes."""
    if is_empty(value):
        return  # collectors never clear a field
    if name in ADD_ONLY_URL_LISTS:
        added = urls_to_add(current[name], value)
        if not added:
            plan.agreeing.add(name)
        elif locked:
            plan.drafts.append(
                _field_draft(ctx, record_id, name, current[name], added, add_only=True)
            )
        else:
            plan.write(name, [*current[name], *added], ctx.candidate.snapshots_of(name))
        return
    if values_equal(ctx.spec.field(name), current[name], value):
        plan.agreeing.add(name)
    elif locked:
        plan.drafts.append(_field_draft(ctx, record_id, name, current[name], value, add_only=False))
    else:
        plan.write(name, value, ctx.candidate.snapshots_of(name))


def _decide_proposal(
    ctx: _Context, plan: _Plan, record_id: str, name: str, value: Any, current: Mapping[str, Any]
) -> None:
    """A propose-only field: a differing value is always a proposal."""
    if is_empty(value):
        return
    base = plan.changes.get(name, current[name])
    if name in ADD_ONLY_URL_LISTS:
        added = urls_to_add(base, value)
        if added:
            plan.drafts.append(_field_draft(ctx, record_id, name, base, added, add_only=True))
        else:
            plan.agreeing.add(name)
    elif values_equal(ctx.spec.field(name), base, value):
        plan.agreeing.add(name)
    else:
        plan.drafts.append(_field_draft(ctx, record_id, name, base, value, add_only=False))


def _update(ctx: _Context, record_id: str, row: Row) -> Outcome:
    """Reconcile the candidate with its bound record (§15.5-§15.9)."""
    spec, session = ctx.spec, ctx.session
    links = load_links(session, [record_id])[record_id] if spec.has_field("links") else None
    current = stored_values(spec, row, links)
    meta = field_meta_of(spec, row)
    judged = row["verification_status"] in JUDGED
    plan = _Plan()
    create_only = CREATE_ONLY.get(spec.name, frozenset())
    writes = {k: v for k, v in ctx.prepared.fields.items() if k not in create_only}
    for name, value in _known_codes(ctx, writes, current, record_id).items():
        locked = judged or (
            not spec.field(name).system and bool((meta.get(name) or {}).get("locked"))
        )
        _decide_write(ctx, plan, record_id, name, value, current, locked)
    for name, value in _known_codes(ctx, ctx.prepared.proposed, current, record_id).items():
        _decide_proposal(ctx, plan, record_id, name, value, current)
    tagging = _plan_document(ctx, plan, record_id, row, current, meta, judged)
    revision = _write_update(ctx, row, plan)
    for draft in plan.drafts:
        ctx.propose(draft)
    drafted = {draft.field for draft in plan.drafts}
    for name in sorted(plan.agreeing - drafted):
        supersede_agreeing(
            session,
            collector=ctx.scope.collector,
            subject_id=record_id,
            field_name=name,
            run_id=ctx.scope.run_id,
            now=ctx.now,
            effects=ctx.effects,
        )
    if tagging is not None:
        document = {**current, **plan.changes, "id": record_id}
        for draft in docs.event_drafts(document, tagging):
            ctx.propose(draft)
        duplicate_candidates(ctx.scope).setdefault("document", set()).add(record_id)
    _remember(ctx, record_id)
    if revision is not None:
        return Outcome("updated", record_id, tuple(ctx.proposals))
    return Outcome("proposed" if ctx.proposals else "unchanged", record_id, tuple(ctx.proposals))


def _plan_document(
    ctx: _Context,
    plan: _Plan,
    record_id: str,
    row: Row,
    current: Mapping[str, Any],
    meta: Mapping[str, Any],
    judged: bool,
) -> docs.Tagging | None:
    """The text version (§15.6) and suggested links (§15.8) of a document candidate;
    returns the tagging of a text written in this unit (for its event proposals)."""
    if ctx.spec.name != "document":
        return None
    version = docs.text_version_of(ctx.session, ctx.candidate)
    tagging = None
    if version is not None and version.text is not None:
        if version.text_hash == current["text_hash"]:
            plan.agreeing.add("text_hash")
        else:
            docs.store_text(ctx.session, version.text, ctx.now)
            retrieved_locked = bool((meta.get("retrieved_at") or {}).get("locked"))
            if row["source_id"] == ctx.scope.collector and not retrieved_locked and not judged:
                for name, value in version.values().items():
                    plan.write(name, value, [version.raw_snapshot_id])
                language = plan.changes.get("language", current["language"])
                tagging = docs.tag_text(ctx.session, version.text, language, ctx.scope.memory)
            else:
                plan.drafts.append(
                    docs.text_version_draft(
                        collector=ctx.scope.collector,
                        document_id=record_id,
                        current_hash=current["text_hash"],
                        version=version,
                        source_url=ctx.candidate.evidence.source_url,
                    )
                )
    added = docs.links_to_add(
        current["links"],
        docs.hinted_links(ctx.session, ctx.scope.collector, ctx.candidate.links),
        docs.tagged_links(tagging) if tagging is not None else [],
    )
    if added:
        plan.write("links", [*current["links"], *added], ctx.candidate.snapshots_of("links"))
        ctx.effects.count("links_suggested", len(added))
    return tagging


def _write_update(ctx: _Context, row: Row, plan: _Plan) -> int | None:
    """All direct writes of the candidate as one revision; None if nothing changed."""
    if not plan.changes:
        return None
    provided = normalize_changes(ctx.unit, plan.changes, creating=False)
    result = update_record(
        ctx.unit, row, provided, note=None, batch_id=None, field_snapshots=plan.snapshots
    )
    if not result.changed:
        return None
    ctx.effects.count("entities_updated")
    ctx.effects.count("revisions")
    if ctx.spec.name in ("project", "service"):
        docs.aliases_changed(ctx.scope.memory)
    return result.revision_id


# --------------------------------------------------------------------------------------
# New records (§15.4)
# --------------------------------------------------------------------------------------


def _missing_required(spec: EntityTypeSpec, values: Mapping[str, Any]) -> list[str]:
    """The required fields (and name constraints) a create would lack."""
    missing = [
        field_spec.name
        for field_spec in spec.stored_fields
        if field_spec.required
        and field_spec.default is None
        and is_empty(values.get(field_spec.name))
    ]
    for constraint in spec.constraints:
        names = constraint.get("one_of_required")
        if names and all(is_empty(values.get(name)) for name in names):
            missing.append(" or ".join(names))
    return missing


def _create(ctx: _Context, seen: SeenObservation, match: _Match) -> Outcome:
    """A direct create on channel ``collector``, bound to the key (``bound_by = auto``);
    with several live matches, a ``possible_duplicate`` proposal names each of them."""
    spec, candidate = ctx.spec, ctx.candidate
    values = {
        name: value
        for name, value in _known_codes(ctx, ctx.prepared.fields, None, None).items()
        if not is_empty(value)
    }
    missing = _missing_required(spec, values)
    if missing:
        ctx.message(
            "warning",
            "incomplete_candidate",
            f"{candidate.key}: no {spec.label.lower()} was created; missing {', '.join(missing)}",
            details={"key": candidate.key, "missing": missing},
        )
        return Outcome("observed")
    snapshots = {name: candidate.snapshots_of(name) for name in values}
    tagging: docs.Tagging | None = None
    added: list[dict[str, Any]] = []
    if spec.name == "document":
        tagging, added = _new_document_values(ctx, values, snapshots)
    provided = normalize_changes(ctx.unit, values, creating=True)
    result = create_record(ctx.unit, provided, note=None, batch_id=None, field_snapshots=snapshots)
    record_id = result.entity_id
    bind_observation(ctx.session, seen.id, record_id, "auto", ctx.now)
    ctx.effects.count("entities_created")
    ctx.effects.count("revisions")
    ctx.effects.count("links_suggested", len(added))
    if spec.name in ("project", "service"):
        docs.aliases_changed(ctx.scope.memory)
    created = {
        **{field_spec.name: field_spec.empty_value() for field_spec in spec.stored_fields},
        **provided,
    }
    plan = _Plan()
    for name, value in _known_codes(ctx, ctx.prepared.proposed, created, record_id).items():
        _decide_proposal(ctx, plan, record_id, name, value, created)
    for draft in plan.drafts:
        ctx.propose(draft)
    if tagging is not None:
        for draft in docs.event_drafts({**created, "id": record_id}, tagging):
            ctx.propose(draft)
    for other in match.candidates:
        first, second = sorted((record_id, other))
        pair = DuplicatePair(
            first, second, MATCH_BASIS, details={"rule": match.rule, "key": candidate.key}
        )
        raised = raise_duplicate(
            ctx.session,
            pair,
            collector=ctx.scope.collector,
            run_id=ctx.scope.run_id,
            now=ctx.now,
            effects=ctx.effects,
        )
        if raised is not None and raised.proposal_id is not None:
            ctx.proposals.append(raised.proposal_id)
    if spec.name in ("document", "service"):
        duplicate_candidates(ctx.scope).setdefault(spec.name, set()).add(record_id)
    _remember(ctx, record_id)
    return Outcome("created", record_id, tuple(ctx.proposals))


def _new_document_values(
    ctx: _Context, values: dict[str, Any], snapshots: dict[str, list[str]]
) -> tuple[docs.Tagging | None, list[dict[str, Any]]]:
    """The system fields of a new document: its source, the text version and suggested
    links; returns the tagging of its text and the links added."""
    candidate = ctx.candidate
    main = [candidate.evidence.raw_snapshot_id]
    values["source_id"] = ctx.scope.collector
    snapshots["source_id"] = main
    if candidate.external_id:
        values["external_id"] = candidate.external_id
        snapshots["external_id"] = main
    version = docs.text_version_of(ctx.session, candidate)
    tagging = None
    if version is not None:
        for name, value in version.values().items():
            if value is not None:
                values[name] = value
                snapshots[name] = [version.raw_snapshot_id]
        if version.text is not None:
            docs.store_text(ctx.session, version.text, ctx.now)
            tagging = docs.tag_text(
                ctx.session, version.text, values.get("language"), ctx.scope.memory
            )
    added = docs.links_to_add(
        [],
        docs.hinted_links(ctx.session, ctx.scope.collector, candidate.links),
        docs.tagged_links(tagging) if tagging is not None else [],
    )
    if added:
        values["links"] = added
        snapshots["links"] = candidate.snapshots_of("links")
    return tagging, added


def site_slug(candidate: Candidate) -> str:
    """The source's slug of an entry (``details.site_slug``, else the key without its
    prefix, e.g. ``entry:brave1`` → ``brave1``), from which a new project's slug is made."""
    given = candidate.details.get("site_slug")
    if isinstance(given, str) and given:
        return given
    return candidate.key.split(":", 1)[-1]


def _propose_create(ctx: _Context, seen: SeenObservation, candidates: Sequence[str]) -> Outcome:
    """A ``create_entity`` proposal for an unmatched key; its observation stays unbound
    until the proposal is accepted (§15.4)."""
    candidate = ctx.candidate
    observed = {
        name: value
        for name, value in _known_codes(ctx, ctx.prepared.fields, None, None).items()
        if not is_empty(value)
    }
    evidence = candidate.evidence
    draft = ProposalDraft(
        kind="create_entity",
        entity_type=ctx.spec.name,
        collector=ctx.scope.collector,
        target=candidate.key,
        core=None,
        payload={
            "fields": observed,
            "field_snapshots": {name: candidate.snapshots_of(name) for name in observed},
            "candidates": list(candidates),
            "observation_key": candidate.key,
            "site_slug": site_slug(candidate),
        },
        raw_snapshot_id=evidence.raw_snapshot_id,
        source_url=evidence.source_url,
        quote=evidence.quote,
        locator=evidence.locator,
        observation_id=seen.id,
    )
    if ctx.propose(draft):
        return Outcome("proposed", None, tuple(ctx.proposals))
    return Outcome("observed")


# --------------------------------------------------------------------------------------
# first_archived events (§15.12)
# --------------------------------------------------------------------------------------

FIRST_ARCHIVED: Final = "first_archived"
ARCHIVE_UPPER_BOUND: Final = "archive_upper_bound"
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


def archive_key(url: str) -> str:
    """The key under which C5 compares URLs (docs/COLLECTORS.md §8.5): lower-cased host
    without ``www.`` and trailing dot, no default port, query and fragment removed, path
    lower-cased without a trailing slash. A URL without a scheme counts as ``http``."""
    text = url.strip()
    parts = urlsplit(text if "://" in text else f"http://{text}")
    host = (parts.hostname or "").rstrip(".")
    host = host.removeprefix("www.")
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and port != _DEFAULT_PORTS.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    return host + parts.path.lower().rstrip("/")


def _archive_values(
    capture: Capture, subject_id: str, day: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The event and evidence values of a capture (§15.12)."""
    event = {
        "subject_id": subject_id,
        "event_type": FIRST_ARCHIVED,
        "date": day,
        "date_basis": ARCHIVE_UPPER_BOUND,
        "date_text": f"{capture.timestamp} {capture.original}"[
            : EVENT.field("date_text").max_length
        ],
        "description_en": (
            f"Earliest capture in the Wayback Machine (CDX, status 200) of {capture.original}"
        ),
    }
    evidence = {
        "url": capture.request_url,
        "archive_url": capture.archive_url,
        "raw_snapshot_id": capture.raw_snapshot_id,
        "retrieved_at": capture.fetched_at,
        "quote": json.dumps(list(capture.cdx_row), ensure_ascii=False)[:MAX_QUOTE_CHARS],
    }
    return event, evidence


def _archive_bound_exists(session: Session, subject_id: str, day: str, collector: str) -> bool:
    """A live ``first_archived`` event of the subject (from anyone), or a deleted one this
    collector created, that ends on or before ``day`` makes a capture redundant."""
    table = Event.__table__
    assert isinstance(table, Table)
    found = session.execute(
        select(table.c.id)
        .where(
            table.c.subject_id == subject_id,
            table.c.event_type == FIRST_ARCHIVED,
            table.c.date_end <= day,
            or_(table.c.deleted_at.is_(None), table.c.created_by == f"collector:{collector}"),
        )
        .limit(1)
    ).first()
    return found is not None


def record_first_archived(
    session: Session, scope: RunScope, subject_id: str, capture: Capture, *, exact: bool
) -> Outcome:
    """Record the earliest Wayback capture of one of the subject's URLs (DATA_MODEL
    §15.12): a ``first_archived`` event with evidence for an exact match, else a
    ``create_event`` proposal; nothing when an existing bound makes it redundant."""
    day = kyiv_date_of_wayback_timestamp(capture.timestamp)
    if day is None:
        raise ValueError(f"not a 14-digit Wayback timestamp: {capture.timestamp!r}")
    effects = RunEffects()
    try:
        with write_transaction(session):
            outcome = _first_archived(session, scope, subject_id, capture, day, exact, effects)
    except DomainError as exc:
        effects = RunEffects()
        effects.message(
            "error",
            "write_error",
            f"capture of {capture.original} for {subject_id}: {exc.message}",
            url=capture.archive_url,
            snapshot_id=capture.raw_snapshot_id,
            subject_id=subject_id,
            details={"error": exc.to_dict()},
        )
        outcome = Outcome("observed")
    effects.report(scope)
    return outcome


def _first_archived(
    session: Session,
    scope: RunScope,
    subject_id: str,
    capture: Capture,
    day: str,
    exact: bool,
    effects: RunEffects,
) -> Outcome:
    now = utc_now()
    resolved = resolve_subject(session, subject_id)
    if resolved is None or resolved[1]["deleted_at"] is not None:
        effects.message(
            "info",
            "subject_deleted",
            f"capture of {capture.original}: the record {subject_id} is deleted",
            url=capture.archive_url,
            snapshot_id=capture.raw_snapshot_id,
            subject_id=subject_id,
        )
        return Outcome("blocked", subject_id)
    record_id = resolved[0]
    if _archive_bound_exists(session, record_id, day, scope.collector):
        return Outcome("unchanged", record_id)
    event, evidence = _archive_values(capture, record_id, day)
    if not exact:
        draft = ProposalDraft(
            kind="create_event",
            entity_type="event",
            collector=scope.collector,
            target=record_id,
            core=[FIRST_ARCHIVED, archive_key(capture.original)],
            subject_id=record_id,
            payload={
                "event": event,
                "evidence": {
                    "document_id": None,
                    "text_hash": None,
                    "char_start": None,
                    "char_end": None,
                    "url": evidence["url"],
                    "archive_url": evidence["archive_url"],
                    "raw_snapshot_id": evidence["raw_snapshot_id"],
                    "retrieved_at": evidence["retrieved_at"],
                },
                "pattern_id": None,
                "matched_alias": None,
            },
            raw_snapshot_id=capture.raw_snapshot_id,
            source_url=capture.request_url,
            quote=evidence["quote"],
        )
        raised = raise_proposal(session, draft, run_id=scope.run_id, now=now, effects=effects)
        if raised.proposal_id is None:
            return Outcome("unchanged", record_id)
        return Outcome("proposed", record_id, (raised.proposal_id,))
    actor = Actor.collector(scope.collector, scope.run_id)
    batch_id = new_batch_id()
    snapshots = [capture.raw_snapshot_id]
    event_unit = WriteUnit.open(session, EVENT, actor)
    created = create_record(
        event_unit,
        normalize_changes(event_unit, event, creating=True),
        note=None,
        batch_id=batch_id,
        field_snapshots=dict.fromkeys(event, snapshots),
    )
    evidence_unit = event_unit.for_type(EVIDENCE)
    values = {"subject_id": created.entity_id, "target": "entity", **evidence}
    create_record(
        evidence_unit,
        normalize_changes(evidence_unit, values, creating=True),
        note=None,
        batch_id=batch_id,
        field_snapshots=dict.fromkeys(values, snapshots),
    )
    effects.count("entities_created", 2)
    effects.count("revisions", 2)
    return Outcome("created", created.entity_id)
