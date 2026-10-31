"""The tagger: alias matching and event patterns over document texts (docs/COLLECTORS.md
§7.6, §7.7, §8.6), and the built-in collector ``tagger``.

**Aliases** are the ``aliases`` of live projects and services (all kinds) plus each record's
``name_en`` and ``name_uk`` as case-sensitive aliases of kind ``name``. Matching runs on the
text normalised with ``normalize_for_search``: an alias with ``case_sensitive: true``
matches exactly, otherwise case-folded; a match must not be preceded or followed by a letter
or digit; overlapping matches are resolved longest first (``Дія.Бізнес`` wins over ``Дія`` at
the same place; equal spans of several subjects all count); a match covered by an occurrence
of one of the alias's ``exclude_patterns`` (literal phrases, case-folded) is dropped. There
is no stemming: inflected forms are aliases of kind ``inflection`` that a person adds.

**Event suggestions:** a sentence of the stored text (docs/COLLECTORS.md §7.7) with an alias
match and an event-pattern match yields one suggestion per (subject, event type), with the
sentence's offsets in the stored text and the sentence as the quote. Suggestions are never
facts: the domain layer turns them into ``create_event`` proposals (DATA_MODEL §15.9), and
link suggestions into suggested document links (§15.8).

Everything here is pure except :func:`load_alias_index` (a read) and the collector, whose
writes go through the run context.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.collectors.base import RunContext, TypeDeclaration
from mdt.collectors.event_patterns import EventPatterns
from mdt.collectors.parsing.texts import clip_quote, sentence_spans, snippet
from mdt.db.models import Project, Service
from mdt.domain.text import normalize_for_search

SNIPPET_CONTEXT = 120


@dataclass(frozen=True)
class Alias:
    """One alias of a subject: the text as curated and how it matches."""

    subject_id: str
    text: str
    case_sensitive: bool = True
    exclude_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class AliasMatch:
    """An accepted alias match; offsets refer to the text given to :meth:`AliasIndex.matches`
    after ``normalize_for_search``."""

    subject_id: str
    alias: str
    start: int
    end: int


@dataclass(frozen=True)
class LinkSuggestion:
    """A suggested link of a document to a subject (DATA_MODEL §15.8)."""

    subject_id: str
    matched_aliases: tuple[str, ...]
    match_count: int
    snippet: str


@dataclass(frozen=True)
class EventSuggestion:
    """A sentence with an alias match and an event-pattern match (DATA_MODEL §15.9).
    ``char_start``/``char_end`` are offsets into the stored text and ``quote`` is
    ``text[char_start:char_end]`` (at most 1 000 characters)."""

    subject_id: str
    event_type: str
    pattern_id: str
    matched_alias: str
    char_start: int
    char_end: int
    quote: str


@dataclass(frozen=True)
class _Prepared:
    """A text in the two forms aliases are matched against. ``offsets`` maps positions of
    the folded text to the normalised text; None when case folding kept every character's
    length (the usual case), so positions agree."""

    normalized: str
    folded: str
    offsets: tuple[int, ...] | None = field(default=None, repr=False)

    @classmethod
    def of(cls, text: str) -> _Prepared:
        normalized = normalize_for_search(text)
        folded = normalized.casefold()
        if len(folded) == len(normalized):  # folding never shortens a character
            return cls(normalized, folded)
        offsets: list[int] = []
        for index, char in enumerate(normalized):
            offsets.extend([index] * len(char.casefold()))
        offsets.append(len(normalized))
        return cls(normalized, folded, tuple(offsets))

    def span(self, start: int, end: int, *, folded: bool) -> tuple[int, int]:
        """A span of the folded (or normalised) text as offsets of the normalised text."""
        if not folded or self.offsets is None:
            return start, end
        return self.offsets[start], self.offsets[end - 1] + 1


def _occurrences(haystack: str, needle: str) -> Iterable[int]:
    start = haystack.find(needle)
    while start != -1:
        yield start
        start = haystack.find(needle, start + 1)


def _is_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return not before.isalnum() and not after.isalnum()


def _has_word_character(text: str) -> bool:
    return any(char.isalnum() for char in text)


@dataclass(frozen=True)
class _Needle:
    """An alias prepared for matching: the text to search and the exclusions to apply."""

    alias: Alias
    text: str
    folded: bool
    excludes: tuple[str, ...]


class AliasIndex:
    """The aliases of the live projects and services, ready for matching."""

    def __init__(self, aliases: Iterable[Alias]) -> None:
        needles: dict[tuple[str, str, bool], _Needle] = {}
        for alias in aliases:
            text = normalize_for_search(alias.text).strip()
            if not _has_word_character(text):
                continue
            folded = not alias.case_sensitive
            needle = text.casefold() if folded else text
            excludes = tuple(
                phrase
                for phrase in (
                    normalize_for_search(item).strip().casefold() for item in alias.exclude_patterns
                )
                if phrase
            )
            needles.setdefault(
                (alias.subject_id, needle, folded), _Needle(alias, needle, folded, excludes)
            )
        self._needles = tuple(needles.values())

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> AliasIndex:
        """An index of records in API representation: ``id``, ``aliases`` (alias items of
        DATA_MODEL §1.2), ``name_en`` and ``name_uk``."""
        aliases: list[Alias] = []
        for record in records:
            subject_id = str(record["id"])
            for item in record.get("aliases") or ():
                aliases.append(
                    Alias(
                        subject_id=subject_id,
                        text=str(item.get("text") or ""),
                        case_sensitive=bool(item.get("case_sensitive", True)),
                        exclude_patterns=tuple(item.get("exclude_patterns") or ()),
                    )
                )
            for name_field in ("name_en", "name_uk"):
                name = record.get(name_field)
                if name:
                    aliases.append(Alias(subject_id=subject_id, text=str(name)))
        return cls(aliases)

    def __len__(self) -> int:
        return len(self._needles)

    def matches(self, text: str) -> list[AliasMatch]:
        """The accepted matches in ``text``, ordered by position (then subject)."""
        prepared = _Prepared.of(text)
        candidates: list[AliasMatch] = []
        for needle in self._needles:
            candidates.extend(_needle_matches(prepared, needle))
        return _resolve_overlaps(candidates)

    def suggest_links(self, text: str) -> list[LinkSuggestion]:
        """Per subject with at least one match: the distinct matched alias texts (sorted),
        the number of matches and a snippet around the first match, sorted by subject."""
        matches = self.matches(text)
        normalized = normalize_for_search(text)
        by_subject: dict[str, list[AliasMatch]] = {}
        for match in matches:
            by_subject.setdefault(match.subject_id, []).append(match)
        suggestions = []
        for subject_id in sorted(by_subject):
            found = by_subject[subject_id]
            first = found[0]
            suggestions.append(
                LinkSuggestion(
                    subject_id=subject_id,
                    matched_aliases=tuple(sorted({match.alias for match in found})),
                    match_count=len(found),
                    snippet=snippet(normalized, first.start, first.end, SNIPPET_CONTEXT),
                )
            )
        return suggestions


def _needle_matches(prepared: _Prepared, needle: _Needle) -> list[AliasMatch]:
    haystack = prepared.folded if needle.folded else prepared.normalized
    excluded = [
        prepared.span(position, position + len(phrase), folded=True)
        for phrase in needle.excludes
        for position in _occurrences(prepared.folded, phrase)
    ]
    found: list[AliasMatch] = []
    for position in _occurrences(haystack, needle.text):
        start, end = prepared.span(position, position + len(needle.text), folded=needle.folded)
        if not _is_boundary(prepared.normalized, start, end):
            continue
        if any(low <= start and end <= high for low, high in excluded):
            continue
        found.append(AliasMatch(needle.alias.subject_id, needle.alias.text, start, end))
    return found


def _resolve_overlaps(candidates: Sequence[AliasMatch]) -> list[AliasMatch]:
    """Longest first; a match overlapping an accepted match with another span is dropped,
    while equal spans (several subjects or aliases) are all kept once per subject."""
    ordered = sorted(candidates, key=lambda m: (-(m.end - m.start), m.start, m.subject_id, m.alias))
    starts: list[int] = []  # accepted distinct spans, sorted by start
    spans: list[tuple[int, int]] = []
    accepted: dict[tuple[str, int, int], AliasMatch] = {}
    for match in ordered:
        span = (match.start, match.end)
        index = bisect.bisect_left(starts, match.start)
        same = index < len(spans) and spans[index] == span
        if not same and _overlaps(spans, index, span):
            continue
        if not same:
            starts.insert(index, match.start)
            spans.insert(index, span)
        accepted.setdefault((match.subject_id, match.start, match.end), match)
    return sorted(accepted.values(), key=lambda m: (m.start, m.end, m.subject_id, m.alias))


def _overlaps(spans: list[tuple[int, int]], index: int, span: tuple[int, int]) -> bool:
    start, end = span
    if index < len(spans) and spans[index][0] < end:
        return True
    return index > 0 and spans[index - 1][1] > start


def suggest_events(
    text: str, language: str | None, index: AliasIndex, patterns: EventPatterns
) -> list[EventSuggestion]:
    """Event suggestions of a stored text: per sentence with an alias match and a pattern
    match, one per (subject, event type), with the first matching pattern (file order) and
    the subject's first alias in the sentence. Patterns apply to their ``lang``; a text
    without a language gets all of them."""
    applicable = EventPatterns(patterns.for_language(language))
    suggestions: list[EventSuggestion] = []
    for start, end in sentence_spans(text):
        sentence = text[start:end]
        matched = applicable.matching(sentence, None)
        if not matched:
            continue
        first_alias: dict[str, str] = {}
        for match in index.matches(sentence):
            first_alias.setdefault(match.subject_id, match.alias)
        if not first_alias:
            continue
        quote = clip_quote(sentence)
        for subject_id in sorted(first_alias):
            seen_types: set[str] = set()
            for pattern in matched:
                if pattern.event_type in seen_types:
                    continue
                seen_types.add(pattern.event_type)
                suggestions.append(
                    EventSuggestion(
                        subject_id=subject_id,
                        event_type=pattern.event_type,
                        pattern_id=pattern.id,
                        matched_alias=first_alias[subject_id],
                        char_start=start,
                        char_end=start + len(quote),
                        quote=quote,
                    )
                )
    return suggestions


def load_alias_index(session: Session) -> AliasIndex:
    """The alias index of the live projects and services. Runs plain selects, so call it
    inside a read or write unit."""
    records: list[dict[str, Any]] = []
    for model in (Project, Service):
        rows = session.execute(
            select(model.id, model.aliases, model.name_en, model.name_uk)
            .where(model.deleted_at.is_(None))
            .order_by(model.id)
        )
        records.extend(
            {"id": row.id, "aliases": row.aliases, "name_en": row.name_en, "name_uk": row.name_uk}
            for row in rows
        )
    return AliasIndex.from_records(records)


# --------------------------------------------------------------------------------------
# The built-in collector (docs/COLLECTORS.md §8.6)
# --------------------------------------------------------------------------------------


class TaggerCollector:
    """The built-in ``tagger``: no network, no records, no observations. It tags every
    live document with a text, or the documents of ``params.document_ids``, in ID order;
    a second run over unchanged data writes nothing."""

    NAME = "tagger"
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {
        "document": TypeDeclaration(creates=False, writes=frozenset({"links"}))
    }
    MODES: tuple[str, ...] = ()
    PARAMS: frozenset[str] = frozenset({"document_ids"})

    def run(self, ctx: RunContext) -> None:
        """Tag the documents; the cancel flag is checked before every document."""
        wanted = ctx.params.get("document_ids")
        documents = [
            record
            for record in ctx.live_records("document", ["text_hash"])
            if record["text_hash"] and (wanted is None or record["id"] in wanted)
        ]
        ctx.count("documents_selected", len(documents))
        for record in documents:
            if ctx.cancelled():
                return
            outcome = ctx.tag_document(record["id"])
            ctx.count("documents_tagged")
            if outcome.action == "updated":
                ctx.count("documents_linked")


COLLECTOR = TaggerCollector()
