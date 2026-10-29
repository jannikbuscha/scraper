"""Vocabularies and codebook parameters (docs/DATA_MODEL.md §7, §9).

The YAML files in ``codebook/`` are loaded by the seed; afterwards the database holds
the working copy of the terms. :class:`TermIndex` answers code lookups inside a write
unit; :func:`load_parameters` reads the cut-off dates from ``parameters.yaml``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import Vocabulary, VocabularyTerm
from mdt.domain.dates import PartialDateError, coerce_date
from mdt.domain.registry import PeriodParameters

PARAMETERS_FILE = "parameters.yaml"
TERM_KEYS = (
    "code",
    "label_en",
    "label_uk",
    "definition",
    "include_note",
    "exclude_note",
    "examples",
    "sort_order",
    "active",
    "replaced_by",
    "attributes",
)
#: Vocabularies whose codes are used by program logic (DATA_MODEL §7).
SYSTEM_VOCABULARIES = (
    "verification_status",
    "screening_status",
    "date_basis",
    "date_precision",
    "period",
    "war_trajectory",
    "derived_reason",
)


class CodebookError(ValueError):
    """A codebook file is malformed."""


@dataclass(frozen=True)
class VocabularyFile:
    """One vocabulary as defined in ``codebook/<name>.yaml``."""

    name: str
    label: str
    description: str | None
    multi: bool
    fixed_codes: bool
    source_file: str
    terms: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Parameters:
    """``codebook/parameters.yaml``: cut-off dates and time zones."""

    ministry_founded: date
    full_scale_invasion: date
    publication_timezone: str | None = None
    storage_timezone: str | None = None

    @property
    def period(self) -> PeriodParameters:
        """The two cut-off dates."""
        return PeriodParameters(self.ministry_founded, self.full_scale_invasion)

    def as_api(self) -> dict[str, str]:
        """The ``parameters`` object of ``GET /api/meta``."""
        return {
            "ministry_founded": self.ministry_founded.isoformat(),
            "full_scale_invasion": self.full_scale_invasion.isoformat(),
        }


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CodebookError(f"{path.name}: invalid YAML") from exc


def _parse_term(raw: Any, source: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CodebookError(f"{source}: every term must be a mapping")
    unknown = set(raw) - set(TERM_KEYS)
    if unknown:
        raise CodebookError(f"{source}: unknown term keys {sorted(unknown)}")
    if not raw.get("code") or not raw.get("label_en"):
        raise CodebookError(f"{source}: every term needs a code and label_en")
    term = {key: raw.get(key) for key in TERM_KEYS}
    term["active"] = True if raw.get("active") is None else raw["active"]
    return term


def load_vocabulary_files(codebook_dir: Path) -> list[VocabularyFile]:
    """Read every ``*.yaml`` vocabulary file (sorted by name).

    ``parameters.yaml`` and files without a ``vocabulary`` key are skipped.
    """
    vocabularies = []
    for path in sorted(codebook_dir.glob("*.yaml")):
        if path.name == PARAMETERS_FILE:
            continue
        data = _read_yaml(path)
        if not isinstance(data, dict) or "vocabulary" not in data:
            continue
        terms = data.get("terms")
        if terms is None:
            terms = []
        if not isinstance(terms, list):
            raise CodebookError(f"{path.name}: terms must be a list")
        vocabularies.append(
            VocabularyFile(
                name=str(data["vocabulary"]),
                label=str(data.get("label") or data["vocabulary"]),
                description=data.get("description"),
                multi=bool(data.get("multi", False)),
                fixed_codes=bool(data.get("fixed_codes", False)),
                source_file=path.name,
                terms=tuple(_parse_term(term, path.name) for term in terms),
            )
        )
    names = [vocabulary.name for vocabulary in vocabularies]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise CodebookError(f"vocabularies defined twice: {sorted(duplicates)}")
    return vocabularies


@lru_cache(maxsize=8)
def _load_parameters_cached(path: str, _mtime_ns: int, _size: int) -> Parameters:
    data = _read_yaml(Path(path))
    if not isinstance(data, dict):
        raise CodebookError(f"{PARAMETERS_FILE}: expected a mapping")
    try:
        ministry = coerce_date(data.get("ministry_founded"))
        invasion = coerce_date(data.get("full_scale_invasion"))
    except PartialDateError as exc:
        raise CodebookError(
            f"{PARAMETERS_FILE}: ministry_founded and full_scale_invasion must be dates"
        ) from exc
    if not ministry < invasion:
        raise CodebookError(f"{PARAMETERS_FILE}: ministry_founded must precede full_scale_invasion")
    return Parameters(
        ministry_founded=ministry,
        full_scale_invasion=invasion,
        publication_timezone=data.get("publication_timezone"),
        storage_timezone=data.get("storage_timezone"),
    )


def load_parameters(codebook_dir: Path) -> Parameters:
    """Read ``parameters.yaml`` (cached while the file is unchanged)."""
    path = codebook_dir / PARAMETERS_FILE
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise CodebookError(f"{path} is missing") from exc
    return _load_parameters_cached(str(path), stat.st_mtime_ns, stat.st_size)


def parameters_digest(codebook_dir: Path) -> str:
    """SHA-256 of ``parameters.yaml`` (input of the derived-values hash, §8.1)."""
    path = codebook_dir / PARAMETERS_FILE
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise CodebookError(f"{path} is missing") from exc


# --------------------------------------------------------------------------------------
# Database lookups
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TermInfo:
    """What validation and labels need to know about a stored term."""

    id: str
    vocabulary: str
    code: str
    label_en: str
    active: bool
    sort_order: int | None
    attributes: Mapping[str, Any]


@dataclass
class TermIndex:
    """Lazy, per-write-unit cache of vocabulary terms and vocabulary metadata."""

    session: Session
    _terms: dict[str, dict[str, TermInfo]] = field(default_factory=dict)
    _vocabularies: dict[str, Vocabulary | None] = field(default_factory=dict)

    def terms(self, vocabulary: str) -> dict[str, TermInfo]:
        """Terms of ``vocabulary`` by code (empty if the vocabulary is unknown)."""
        if vocabulary not in self._terms:
            self._terms[vocabulary] = load_terms(self.session, vocabulary)
        return self._terms[vocabulary]

    def term(self, vocabulary: str, code: str) -> TermInfo | None:
        """The term ``vocabulary:code`` or None."""
        return self.terms(vocabulary).get(code)

    def vocabulary(self, name: str) -> Vocabulary | None:
        """Vocabulary metadata row or None."""
        if name not in self._vocabularies:
            self._vocabularies[name] = self.session.get(Vocabulary, name)
        return self._vocabularies[name]


def _term_info(term: VocabularyTerm) -> TermInfo:
    attributes = term.attributes if isinstance(term.attributes, dict) else {}
    return TermInfo(
        id=term.id,
        vocabulary=term.vocabulary,
        code=term.code,
        label_en=term.label_en,
        active=bool(term.active),
        sort_order=term.sort_order,
        attributes=attributes,
    )


def load_terms(session: Session, vocabulary: str) -> dict[str, TermInfo]:
    """All terms of ``vocabulary`` by code."""
    rows = session.scalars(select(VocabularyTerm).where(VocabularyTerm.vocabulary == vocabulary))
    return {term.code: _term_info(term) for term in rows}


def term_labels(session: Session, pairs: Iterable[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """English labels for ``(vocabulary, code)`` pairs; unknown codes are omitted."""
    wanted = set(pairs)
    vocabularies = {vocabulary for vocabulary, _ in wanted}
    if not vocabularies:
        return {}
    rows = session.execute(
        select(VocabularyTerm.vocabulary, VocabularyTerm.code, VocabularyTerm.label_en).where(
            VocabularyTerm.vocabulary.in_(vocabularies)
        )
    )
    return {(v, c): label for v, c, label in rows if (v, c) in wanted}


def modification_event_types(session: Session) -> list[str]:
    """Codes of the event types with ``attributes.counts_as_modification = true``."""
    return sorted(
        code
        for code, term in load_terms(session, "event_type").items()
        if term.attributes.get("counts_as_modification") is True
    )


def is_fixed_term(vocabulary: Vocabulary | None, attributes: Mapping[str, Any] | None) -> bool:
    """True if the term's code is fixed (fixed vocabulary or ``attributes.fixed``)."""
    if vocabulary is not None and vocabulary.fixed_codes:
        return True
    return bool(attributes and attributes.get("fixed") is True)
