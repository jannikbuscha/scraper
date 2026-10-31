"""Mapping files: ``codebook/collector_mappings.yaml`` (docs/COLLECTORS.md §7.9).

A codebook file that is not a vocabulary (no ``vocabulary`` key, so the seed skips it). Each
mapping names the collector that uses it, the target vocabulary, the codes with their
source labels, an optional ``fallback`` code for unmapped labels and labels to ``ignore``.
Labels are compared after case folding and whitespace collapsing. Every target code must be
an active term of its vocabulary; otherwise runs of the collectors that use the mapping fail
(:func:`mapping_for_run` raises :class:`~mdt.collectors.base.FatalRunError`).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from mdt.collectors.base import FatalRunError, RunContext
from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.domain.text import fold

MAPPINGS_FILE = "collector_mappings.yaml"
FILE_VERSION = 1
_KEYS = frozenset({"collector", "vocabulary", "fallback", "codes", "ignore"})
_CODE = re.compile(r"^[a-z0-9_]+$")

MappingStatus = Literal["mapped", "ignored", "fallback", "unmapped"]


class MappingError(ValueError):
    """``collector_mappings.yaml`` is malformed or names codes that are not active terms."""


def label_key(label: str) -> str:
    """The comparison form of a source label."""
    return collapse_whitespace(fold(label))


@dataclass(frozen=True)
class MappingResult:
    """The code for one source label: ``mapped``, ``fallback`` (an unmapped label with the
    fallback code), ``unmapped`` (no code; the caller warns ``unmapped_label``) or
    ``ignored`` (no code, no warning)."""

    code: str | None
    status: MappingStatus


@dataclass(frozen=True)
class LabelMapping:
    """One mapping of the file."""

    name: str
    collector: str
    vocabulary: str
    labels: Mapping[str, str]  # label key → code
    fallback: str | None = None
    ignore: frozenset[str] = frozenset()

    def lookup(self, label: str) -> MappingResult:
        """The code of a source label."""
        key = label_key(label)
        if key in self.labels:
            return MappingResult(self.labels[key], "mapped")
        if key in self.ignore:
            return MappingResult(None, "ignored")
        if self.fallback is not None:
            return MappingResult(self.fallback, "fallback")
        return MappingResult(None, "unmapped")

    @property
    def target_codes(self) -> frozenset[str]:
        """Every code the mapping can produce (fallback included)."""
        codes = set(self.labels.values())
        if self.fallback is not None:
            codes.add(self.fallback)
        return frozenset(codes)

    def check_codes(self, active_codes: Collection[str]) -> None:
        """Raise :class:`MappingError` if a target code is not in ``active_codes``."""
        missing = sorted(self.target_codes - set(active_codes))
        if missing:
            raise MappingError(
                f"{MAPPINGS_FILE}: mapping {self.name} uses codes that are not active terms "
                f"of {self.vocabulary}: {', '.join(missing)}"
            )


def _labels(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise MappingError(f"{where}: must be a non-empty list of labels")
    if not all(isinstance(item, str) and label_key(item) for item in value):
        raise MappingError(f"{where}: labels must be non-empty strings")
    return value


def parse_mapping(name: str, entry: Any) -> LabelMapping:
    """Check one mapping of the file."""
    where = f"{MAPPINGS_FILE}: mapping {name}"
    if not isinstance(entry, dict):
        raise MappingError(f"{where}: must be a mapping")
    unknown = set(entry) - _KEYS
    if unknown:
        raise MappingError(f"{where}: unknown keys {sorted(unknown)}")
    collector = entry.get("collector")
    if not isinstance(collector, str) or not _CODE.fullmatch(collector):
        raise MappingError(f"{where}: collector must be a collector key")
    vocabulary = entry.get("vocabulary")
    if not isinstance(vocabulary, str) or not _CODE.fullmatch(vocabulary):
        raise MappingError(f"{where}: vocabulary must be a vocabulary name")
    fallback = entry.get("fallback")
    if fallback is not None and (not isinstance(fallback, str) or not _CODE.fullmatch(fallback)):
        raise MappingError(f"{where}: fallback must be a code")
    codes = entry.get("codes")
    if not isinstance(codes, dict) or not codes:
        raise MappingError(f"{where}: codes must map codes to labels")
    labels: dict[str, str] = {}
    for code, items in codes.items():
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise MappingError(f"{where}: {code!r} is not a code")
        for label in _labels(items, f"{where}, code {code}"):
            key = label_key(label)
            if key in labels:
                raise MappingError(f"{where}: the label {label!r} is mapped twice")
            labels[key] = code
    raw_ignore = entry.get("ignore")
    ignore = (
        frozenset()
        if raw_ignore is None
        else frozenset(label_key(label) for label in _labels(raw_ignore, f"{where}, ignore"))
    )
    overlap = sorted(ignore & set(labels))
    if overlap:
        raise MappingError(f"{where}: labels both mapped and ignored: {overlap}")
    return LabelMapping(name, collector, vocabulary, labels, fallback, ignore)


def parse_mappings(data: Any) -> dict[str, LabelMapping]:
    """Check the content of ``collector_mappings.yaml``."""
    if not isinstance(data, dict):
        raise MappingError(f"{MAPPINGS_FILE}: expected a mapping")
    if "vocabulary" in data:
        raise MappingError(f"{MAPPINGS_FILE}: must not have a vocabulary key")
    if data.get("version") != FILE_VERSION:
        raise MappingError(f"{MAPPINGS_FILE}: version must be {FILE_VERSION}")
    entries = data.get("mappings")
    if not isinstance(entries, dict) or not entries:
        raise MappingError(f"{MAPPINGS_FILE}: mappings must be a non-empty mapping")
    result: dict[str, LabelMapping] = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not _CODE.fullmatch(name):
            raise MappingError(f"{MAPPINGS_FILE}: {name!r} is not a mapping name")
        result[name] = parse_mapping(name, entry)
    return result


@lru_cache(maxsize=4)
def _load_cached(path: str, _mtime_ns: int, _size: int) -> dict[str, LabelMapping]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MappingError(f"{MAPPINGS_FILE}: invalid YAML") from exc
    return parse_mappings(data)


def load_mappings(codebook_dir: Path) -> dict[str, LabelMapping]:
    """Read and check ``<codebook_dir>/collector_mappings.yaml`` (cached while unchanged)."""
    path = codebook_dir / MAPPINGS_FILE
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise MappingError(f"{MAPPINGS_FILE} is missing") from exc
    return dict(_load_cached(str(path), stat.st_mtime_ns, stat.st_size))


def load_mapping(codebook_dir: Path, name: str) -> LabelMapping:
    """One mapping by name; :class:`MappingError` if the file or the name is invalid."""
    mappings = load_mappings(codebook_dir)
    if name not in mappings:
        raise MappingError(f"{MAPPINGS_FILE}: no mapping {name}")
    return mappings[name]


def active_codes(terms: Iterable[Mapping[str, Any]], vocabulary: str) -> set[str]:
    """The active codes of ``vocabulary`` among term records (``vocabulary``, ``code``,
    ``active``), e.g. ``ctx.live_records("vocabulary_term", …)``."""
    return {
        str(term["code"])
        for term in terms
        if term.get("vocabulary") == vocabulary and term.get("active")
    }


def mapping_for_run(ctx: RunContext, name: str) -> LabelMapping:
    """A mapping of the run's codebook directory checked against the active vocabulary
    terms, for a collector run: an invalid file or a code that is not an active term raises
    FatalRunError, so the run fails (docs/COLLECTORS.md §7.9)."""
    try:
        mapping = load_mapping(ctx.settings.codebook_path, name)
        terms = ctx.live_records("vocabulary_term", ["vocabulary", "code", "active"])
        mapping.check_codes(active_codes(terms, mapping.vocabulary))
    except MappingError as exc:
        raise FatalRunError(str(exc)) from exc
    return mapping
