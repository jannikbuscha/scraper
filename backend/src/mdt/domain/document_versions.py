"""Documents in the reconciler: text versions, suggested links and event proposals
(docs/DATA_MODEL.md §15.6, §15.8, §15.9; docs/COLLECTORS.md §7.6-§7.7, §8.6).

* A document's **text version** (``text_hash``, ``raw_snapshot_id``, ``retrieved_at``,
  ``extraction_method``) changes only as a whole; :func:`text_version_of` builds it from a
  candidate and :func:`store_text` keeps the text in ``document_text``.
* **Suggested links** (origin ``auto``, state ``suggested``) are added for subjects that are
  not yet in the document's links in any state: the tagger's alias matches of a new or
  changed text and the links the source itself states. Adding them is an add-only write.
* **Event proposals**: a sentence with an alias match and an event-pattern match becomes a
  ``create_event`` proposal of the collector ``tagger`` with the document's current text
  version as evidence; never a fact.
* :func:`tag_document` is one write unit of the built-in ``tagger`` collector.

The alias matching and the event patterns themselves live in :mod:`mdt.collectors.tagger`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from mdt.collectors.base import LinkHint, Outcome
from mdt.collectors.event_patterns import load_event_patterns
from mdt.collectors.parsing.texts import normalize_document_text, text_hash
from mdt.collectors.tagger import (
    AliasIndex,
    EventSuggestion,
    LinkSuggestion,
    load_alias_index,
    suggest_events,
)
from mdt.db.models import DocumentText, RawSnapshot
from mdt.db.session import session_settings, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.observations import find_observation, resolve_subject
from mdt.domain.proposals import TAGGER, ProposalDraft, raise_proposal
from mdt.domain.records import load_links, load_row, stored_values
from mdt.domain.registry import DOCUMENT
from mdt.domain.run_effects import RunEffects
from mdt.domain.text import fold
from mdt.domain.writes import WriteUnit, normalize_changes, update_record

if TYPE_CHECKING:
    from mdt.collectors.base import Candidate, RunScope

#: The fields of a document's text version, written as one unit (§15.6).
TEXT_VERSION_FIELDS: Final = ("text_hash", "raw_snapshot_id", "retrieved_at", "extraction_method")
#: Run memory: the alias index of the run and whether the run changed names or aliases.
ALIAS_INDEX: Final = "mdt.alias_index"
_STALE: Final = "stale"


# --------------------------------------------------------------------------------------
# Text versions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TextVersion:
    """The text version a candidate observed. ``text`` is the normalised text (None when
    the source gave none, e.g. a listing-only item or a file without a text layer)."""

    text: str | None
    raw_snapshot_id: str
    retrieved_at: str
    extraction_method: str | None

    @property
    def text_hash(self) -> str | None:
        """SHA-256 of the normalised text, or None without a text."""
        return text_hash(self.text) if self.text is not None else None

    def values(self) -> dict[str, Any]:
        """The four fields of the version."""
        return {
            "text_hash": self.text_hash,
            "raw_snapshot_id": self.raw_snapshot_id,
            "retrieved_at": self.retrieved_at,
            "extraction_method": self.extraction_method,
        }


def text_version_of(session: Session, candidate: Candidate) -> TextVersion | None:
    """The text version of a document candidate, or None if it carries none. The snapshot
    is the candidate's ``text_snapshot_id`` (else its main evidence), the retrieval time
    that snapshot's ``fetched_at``."""
    if (
        candidate.text is None
        and candidate.text_snapshot_id is None
        and candidate.extraction_method is None
        and "extraction_method" not in candidate.fields
    ):
        return None
    snapshot_id = (
        candidate.text_snapshot_id
        or candidate.fields.get("raw_snapshot_id")
        or candidate.evidence.raw_snapshot_id
    )
    fetched_at = session.execute(
        select(RawSnapshot.fetched_at).where(RawSnapshot.id == snapshot_id)
    ).scalar()
    if fetched_at is None:
        raise ValueError(f"candidate {candidate.key}: unknown raw snapshot {snapshot_id}")
    text = normalize_document_text(candidate.text) if candidate.text else None
    method = candidate.extraction_method or candidate.fields.get("extraction_method")
    return TextVersion(text or None, str(snapshot_id), str(fetched_at), method)


def store_text(session: Session, text: str, now: str) -> str:
    """Keep a normalised text in ``document_text`` (immutable, content-addressed) and
    return its ``text_hash``."""
    digest = text_hash(text)
    table = DocumentText.__table__
    assert isinstance(table, Table)
    session.execute(
        sqlite_insert(table)
        .values(text_hash=digest, text=text, char_count=len(text), created_at=now)
        .on_conflict_do_nothing(index_elements=["text_hash"])
    )
    return digest


def stored_text(session: Session, digest: str | None) -> str | None:
    """The text of a stored text version, or None."""
    if not digest:
        return None
    return session.execute(
        select(DocumentText.text).where(DocumentText.text_hash == digest)
    ).scalar()


def text_version_draft(
    *,
    collector: str,
    document_id: str,
    current_hash: str | None,
    version: TextVersion,
    source_url: str | None,
) -> ProposalDraft:
    """The ``update_field`` proposal on ``text_hash`` for a new text version that the
    collector may not write directly (§15.6)."""
    return ProposalDraft(
        kind="update_field",
        entity_type="document",
        collector=collector,
        target=document_id,
        core=["text_hash", version.text_hash],
        subject_id=document_id,
        field="text_hash",
        current_value=current_hash,
        proposed_value=version.text_hash,
        payload={
            "raw_snapshot_id": version.raw_snapshot_id,
            "retrieved_at": version.retrieved_at,
            "extraction_method": version.extraction_method,
            "char_count": len(version.text or ""),
        },
        raw_snapshot_id=version.raw_snapshot_id,
        source_url=source_url,
    )


# --------------------------------------------------------------------------------------
# Tagging: aliases and event patterns
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tagging:
    """What the tagger found in one text."""

    links: Sequence[LinkSuggestion]
    events: Sequence[EventSuggestion]


def alias_index(session: Session, memory: dict[str, Any] | None) -> AliasIndex:
    """The alias index of the live projects and services, kept in the run's memory until
    the run changes a project or service (:func:`aliases_changed`)."""
    cached = memory.get(ALIAS_INDEX) if memory is not None else None
    if isinstance(cached, AliasIndex):
        return cached
    index = load_alias_index(session)
    if memory is not None:
        memory[ALIAS_INDEX] = index
    return index


def aliases_changed(memory: dict[str, Any]) -> None:
    """The run wrote a project or service: rebuild the alias index before the next use."""
    memory[ALIAS_INDEX] = _STALE


def tag_text(
    session: Session, text: str, language: str | None, memory: dict[str, Any] | None
) -> Tagging:
    """Run the tagger over a stored text: link suggestions per subject and event
    suggestions per sentence (docs/COLLECTORS.md §7.6, §7.7)."""
    index = alias_index(session, memory)
    patterns = load_event_patterns(session_settings(session).codebook_path)
    return Tagging(index.suggest_links(text), suggest_events(text, language, index, patterns))


# --------------------------------------------------------------------------------------
# Suggested links (§15.8)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SuggestedLink:
    """A link to add: origin ``auto``, state ``suggested``, with the match details."""

    subject_id: str
    matched_aliases: tuple[str, ...]
    match_count: int
    snippet: str | None

    def as_link(self) -> dict[str, Any]:
        """The link item of the document's ``links``."""
        return {
            "subject_id": self.subject_id,
            "origin": "auto",
            "state": "suggested",
            "matched_aliases": list(self.matched_aliases),
            "match_count": self.match_count,
            "snippet": self.snippet,
        }


def hinted_links(
    session: Session, collector: str, hints: Sequence[LinkHint]
) -> list[SuggestedLink]:
    """The links a source itself states, resolved to live records: a record ID, or an
    observation key of the collector through its binding (merged records lead to their
    survivor); unresolvable hints are skipped."""
    found: list[SuggestedLink] = []
    for hint in hints:
        subject_id = hint.subject_id
        if subject_id is None and hint.subject_key is not None:
            observation = find_observation(session, collector, hint.subject_key)
            subject_id = observation["subject_id"] if observation is not None else None
        if not subject_id:
            continue
        resolved = resolve_subject(session, subject_id)
        if resolved is None or resolved[1]["deleted_at"] is not None:
            continue
        found.append(SuggestedLink(resolved[0], (), 0, hint.snippet))
    return found


def tagged_links(tagging: Tagging) -> list[SuggestedLink]:
    """The tagger's link suggestions as links to add."""
    return [
        SuggestedLink(item.subject_id, tuple(item.matched_aliases), item.match_count, item.snippet)
        for item in tagging.links
    ]


def links_to_add(
    current: Sequence[Mapping[str, Any]],
    hinted: Sequence[SuggestedLink],
    tagged: Sequence[SuggestedLink] = (),
) -> list[dict[str, Any]]:
    """Suggested links for subjects that are not yet in the links in any state; a rejected
    subject is never suggested again. A subject the source itself links (``hinted``) keeps
    the source's snippet and takes the tagger's matched aliases and count when the tagger
    found it too; otherwise the first suggestion per subject wins."""
    present = {str(link["subject_id"]) for link in current}
    matches = {item.subject_id: item for item in tagged}
    added: list[dict[str, Any]] = []
    for suggestion in [*hinted, *tagged]:
        if suggestion.subject_id in present:
            continue
        present.add(suggestion.subject_id)
        match = matches.get(suggestion.subject_id)
        if match is not None and not suggestion.matched_aliases:
            suggestion = replace(
                suggestion, matched_aliases=match.matched_aliases, match_count=match.match_count
            )
        added.append(suggestion.as_link())
    return added


# --------------------------------------------------------------------------------------
# Event proposals (§15.9)
# --------------------------------------------------------------------------------------


def event_drafts(document: Mapping[str, Any], tagging: Tagging) -> list[ProposalDraft]:
    """One ``create_event`` proposal per event suggestion of the document's current text
    version: the date is the document's publication date with basis ``inferred`` (an
    announcement date is not automatically the event date), the evidence the sentence."""
    published = document.get("published")
    drafts: list[ProposalDraft] = []
    for item in tagging.events:
        event = {
            "subject_id": item.subject_id,
            "event_type": item.event_type,
            "date": published,
            "date_basis": "inferred" if published else None,
            "date_text": document.get("published_text") if published else None,
            "description_en": None,
        }
        evidence = {
            "document_id": document["id"],
            "text_hash": document.get("text_hash"),
            "char_start": item.char_start,
            "char_end": item.char_end,
            "url": document.get("url"),
            "archive_url": None,
            "raw_snapshot_id": document.get("raw_snapshot_id"),
            "retrieved_at": document.get("retrieved_at"),
        }
        drafts.append(
            ProposalDraft(
                kind="create_event",
                entity_type="event",
                collector=TAGGER,
                target=item.subject_id,
                core=[item.event_type, document["id"], fold(item.quote)],
                subject_id=item.subject_id,
                payload={
                    "event": event,
                    "evidence": evidence,
                    "pattern_id": item.pattern_id,
                    "matched_alias": item.matched_alias,
                },
                raw_snapshot_id=document.get("raw_snapshot_id"),
                source_url=document.get("url"),
                quote=item.quote,
            )
        )
    return drafts


# --------------------------------------------------------------------------------------
# The built-in tagger (docs/COLLECTORS.md §8.6)
# --------------------------------------------------------------------------------------


def tag_document(session: Session, scope: RunScope, document_id: str) -> Outcome:
    """Tag one stored document as one write unit (the built-in ``tagger``, §8.6): run the
    tagger and the event patterns over its current text, add suggested links (a revision
    only when links are added) and raise ``create_event`` proposals. A deleted document or
    one without a text is left as it is."""
    effects = RunEffects()
    proposals: list[str] = []
    revision: int | None = None
    with write_transaction(session):
        now = utc_now()
        row = load_row(session, DOCUMENT, document_id)
        if row is None or row["deleted_at"] is not None:
            return Outcome("unchanged", document_id if row is not None else None)
        links = load_links(session, [document_id])[document_id]
        document = {**stored_values(DOCUMENT, row, links), "id": document_id}
        text = stored_text(session, document["text_hash"])
        if text is None:
            return Outcome("unchanged", document_id)
        tagging = tag_text(session, text, document["language"], scope.memory)
        added = links_to_add(links, (), tagged_links(tagging))
        if added:
            unit = WriteUnit.open(session, DOCUMENT, Actor.collector(scope.collector, scope.run_id))
            snapshot = document["raw_snapshot_id"]
            result = update_record(
                unit,
                row,
                normalize_changes(unit, {"links": [*links, *added]}, creating=False),
                note=None,
                batch_id=None,
                field_snapshots={"links": [snapshot]} if snapshot else None,
            )
            revision = result.revision_id
            effects.count("links_suggested", len(added))
            effects.count("entities_updated")
            effects.count("revisions")
        for draft in event_drafts(document, tagging):
            raised = raise_proposal(session, draft, run_id=scope.run_id, now=now, effects=effects)
            if raised.proposal_id is not None:
                proposals.append(raised.proposal_id)
    effects.report(scope)
    if revision is not None:
        return Outcome("updated", document_id, tuple(proposals))
    return Outcome("proposed" if proposals else "unchanged", document_id, tuple(proposals))
