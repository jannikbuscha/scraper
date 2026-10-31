"""Duplicate detection (docs/COLLECTORS.md §7.8): pairs for ``possible_duplicate`` proposals.

* **Documents:** a document created or with a changed text in the run is compared with the
  live documents of **another** ``source_id`` with the same ``language`` and a ``published``
  date within ±1 day. A pair is a possible duplicate if the titles are equal after
  ``fold()``, whitespace collapsing and removal of punctuation (basis ``title_date``), or if
  the containment of their word 3-shingle sets, |A ∩ B| / min(|A|, |B|), over the first
  5 000 words of the normalised texts is at least 0.8 (basis ``text``, with the similarity).
* **Services** (C3): a new service whose ``name_uk`` equals, after ``fold()``, that of
  another live service of the same project (basis ``name``).

Pairs are ordered (``subject_id`` < ``related_id``), as the proposal of DATA_MODEL §16.1
expects. Both records stay; a person decides. The pure functions take plain values; the
``find_*`` helpers read the database with plain selects inside the caller's unit.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.db.models import Document, DocumentText, Service
from mdt.domain.text import fold

TEXT_THRESHOLD = 0.8
SHINGLE_SIZE = 3
MAX_WORDS = 5000
MAX_DAYS_APART = 1
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class DocumentInfo:
    """What the comparison needs of a document; ``published_*`` are the interval of its
    ``published`` partial date (``YYYY-MM-DD``)."""

    id: str
    source_id: str | None
    language: str | None
    published_start: str | None
    published_end: str | None
    title: str
    text: str | None = None


@dataclass(frozen=True)
class ServiceInfo:
    """What the comparison needs of a service."""

    id: str
    project_id: str
    name_uk: str | None


@dataclass(frozen=True)
class DuplicatePair:
    """A possible duplicate: the two records (ordered) and the basis of the judgement."""

    subject_id: str
    related_id: str
    basis: str  # title_date | text | name
    similarity: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def title_key(title: str) -> str:
    """The comparison form of a title: folded, punctuation removed, whitespace collapsed."""
    folded = fold(title)
    without = "".join(char for char in folded if not unicodedata.category(char).startswith("P"))
    return collapse_whitespace(without)


def word_shingles(text: str) -> frozenset[tuple[str, ...]]:
    """The word 3-shingles of the first 5 000 words of the folded text."""
    words = _WORD.findall(fold(text))[:MAX_WORDS]
    return frozenset(
        tuple(words[index : index + SHINGLE_SIZE]) for index in range(len(words) - SHINGLE_SIZE + 1)
    )


def containment(left: frozenset[tuple[str, ...]], right: frozenset[tuple[str, ...]]) -> float:
    """|A ∩ B| / min(|A|, |B|); 0 when either set is empty."""
    smaller = min(len(left), len(right))
    if not smaller:
        return 0.0
    return len(left & right) / smaller


def days_between(a: DocumentInfo, b: DocumentInfo) -> int | None:
    """Days between the two publication intervals (0 if they overlap); None without a date."""
    if not (a.published_start and a.published_end and b.published_start and b.published_end):
        return None
    later_start = max(date.fromisoformat(a.published_start), date.fromisoformat(b.published_start))
    earlier_end = min(date.fromisoformat(a.published_end), date.fromisoformat(b.published_end))
    return max(0, (later_start - earlier_end).days)


def _ordered(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def document_pair(a: DocumentInfo, b: DocumentInfo) -> DuplicatePair | None:
    """The possible-duplicate judgement of two documents, or None (also when they do not
    qualify: same record or source, other or unknown language, dates too far apart)."""
    if a.id == b.id or a.source_id == b.source_id:
        return None
    if a.language is None or a.language != b.language:
        return None
    days = days_between(a, b)
    if days is None or days > MAX_DAYS_APART:
        return None
    subject_id, related_id = _ordered(a.id, b.id)
    details = {"days_apart": days}
    if title_key(a.title) and title_key(a.title) == title_key(b.title):
        return DuplicatePair(subject_id, related_id, "title_date", None, details)
    if a.text and b.text:
        similarity = containment(word_shingles(a.text), word_shingles(b.text))
        if similarity >= TEXT_THRESHOLD:
            return DuplicatePair(subject_id, related_id, "text", round(similarity, 3), details)
    return None


def document_duplicates(
    changed: Sequence[DocumentInfo], others: Sequence[DocumentInfo]
) -> list[DuplicatePair]:
    """Every pair of a changed document and another document that qualifies, once,
    sorted by the pair's IDs."""
    pairs: dict[tuple[str, str], DuplicatePair] = {}
    for document in changed:
        for other in others:
            pair = document_pair(document, other)
            if pair is not None:
                pairs.setdefault((pair.subject_id, pair.related_id), pair)
    return [pairs[key] for key in sorted(pairs)]


def service_duplicates(
    new: Sequence[ServiceInfo], others: Sequence[ServiceInfo]
) -> list[DuplicatePair]:
    """Every pair of a new service and another service of the same project with the same
    folded ``name_uk``, once, sorted by the pair's IDs."""
    pairs: dict[tuple[str, str], DuplicatePair] = {}
    for service in new:
        if not service.name_uk:
            continue
        key = fold(service.name_uk)
        for other in others:
            if (
                other.id != service.id
                and other.project_id == service.project_id
                and other.name_uk
                and fold(other.name_uk) == key
            ):
                subject_id, related_id = _ordered(service.id, other.id)
                pairs.setdefault(
                    (subject_id, related_id), DuplicatePair(subject_id, related_id, "name")
                )
    return [pairs[key] for key in sorted(pairs)]


# --------------------------------------------------------------------------------------
# Database helpers (plain selects; call them inside a read or write unit)
# --------------------------------------------------------------------------------------


def _document_infos(session: Session, *conditions: Any) -> list[DocumentInfo]:
    query = (
        select(
            Document.id,
            Document.source_id,
            Document.language,
            Document.published_start,
            Document.published_end,
            Document.title,
            DocumentText.text,
        )
        .outerjoin(DocumentText, DocumentText.text_hash == Document.text_hash)
        .where(Document.deleted_at.is_(None), *conditions)
        .order_by(Document.id)
    )
    return [DocumentInfo(*row) for row in session.execute(query)]


def find_document_duplicates(session: Session, document_ids: Iterable[str]) -> list[DuplicatePair]:
    """The possible duplicates of the given (live) documents among the live documents of
    other sources with the same language and a publication date within ±1 day."""
    changed = _document_infos(session, Document.id.in_(sorted(set(document_ids))))
    pairs: dict[tuple[str, str], DuplicatePair] = {}
    for document in changed:
        if document.language is None or document.published_start is None:
            continue
        window_start = date.fromisoformat(document.published_start).toordinal() - MAX_DAYS_APART
        window_end = date.fromisoformat(document.published_end or document.published_start)
        others = _document_infos(
            session,
            Document.language == document.language,
            Document.published_end >= date.fromordinal(window_start).isoformat(),
            Document.published_start
            <= date.fromordinal(window_end.toordinal() + MAX_DAYS_APART).isoformat(),
            Document.id != document.id,
        )
        for pair in document_duplicates([document], others):
            pairs.setdefault((pair.subject_id, pair.related_id), pair)
    return [pairs[key] for key in sorted(pairs)]


def find_service_duplicates(session: Session, service_ids: Iterable[str]) -> list[DuplicatePair]:
    """The possible duplicates of the given (live) services among the live services of
    their projects."""
    columns = (Service.id, Service.project_id, Service.name_uk)
    new = [
        ServiceInfo(*row)
        for row in session.execute(
            select(*columns)
            .where(Service.id.in_(sorted(set(service_ids))), Service.deleted_at.is_(None))
            .order_by(Service.id)
        )
    ]
    projects = sorted({service.project_id for service in new})
    others = [
        ServiceInfo(*row)
        for row in session.execute(
            select(*columns)
            .where(Service.project_id.in_(projects), Service.deleted_at.is_(None))
            .order_by(Service.id)
        )
    ]
    return service_duplicates(new, others)
