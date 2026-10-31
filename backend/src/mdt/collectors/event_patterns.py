"""Event patterns: ``codebook/event_patterns.yaml`` (docs/COLLECTORS.md §7.7).

A codebook file that is not a vocabulary (no ``vocabulary`` key, so the seed skips it). Each
pattern names an ``event_type``, a ``lang`` and at least one of ``stems`` (a word that
starts with the stem), ``phrases`` (a sequence of words; a word written with a trailing
``-`` is a stem) and ``all_of`` (stems that must all occur in the same sentence).

Matching works on one sentence at a time: the sentence is normalised with
``normalize_for_search`` and case-folded, then split into words (runs of letters and digits;
any other non-space character is a word of its own, e.g. ``№``). Pattern texts are folded
the same way when the file is loaded.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from mdt.domain.text import fold

EVENT_PATTERNS_FILE = "event_patterns.yaml"
FILE_VERSION = 1
_KEYS = frozenset({"id", "event_type", "lang", "stems", "phrases", "all_of"})
_CODE = re.compile(r"^[a-z0-9_]+$")
_TOKEN = re.compile(r"[^\W_]+|[^\w\s]|_")
_WORD = re.compile(r"[^\W_]+")


class EventPatternsError(ValueError):
    """``event_patterns.yaml`` is malformed; the message names the entry."""


#: A phrase element: the folded word and whether it is a stem (prefix) or exact.
PhraseWord = tuple[str, bool]


def sentence_tokens(sentence: str) -> list[str]:
    """The words of a sentence after normalisation and case folding."""
    return _TOKEN.findall(fold(sentence))


@dataclass(frozen=True)
class EventPattern:
    """One entry of the file, with its texts folded."""

    id: str
    event_type: str
    lang: str
    stems: tuple[str, ...] = ()
    phrases: tuple[tuple[PhraseWord, ...], ...] = ()
    all_of: tuple[str, ...] = ()

    def matches(self, tokens: Sequence[str]) -> bool:
        """True if the sentence (its :func:`sentence_tokens`) matches the pattern."""
        if any(token.startswith(stem) for stem in self.stems for token in tokens):
            return True
        if any(_phrase_at(tokens, phrase) for phrase in self.phrases):
            return True
        return bool(self.all_of) and all(
            any(token.startswith(stem) for token in tokens) for stem in self.all_of
        )


def _phrase_at(tokens: Sequence[str], phrase: tuple[PhraseWord, ...]) -> bool:
    size = len(phrase)
    for start in range(len(tokens) - size + 1):
        if all(
            tokens[start + offset].startswith(word) if is_stem else tokens[start + offset] == word
            for offset, (word, is_stem) in enumerate(phrase)
        ):
            return True
    return False


@dataclass(frozen=True)
class EventPatterns:
    """The patterns of the file, in file order."""

    patterns: tuple[EventPattern, ...]

    def for_language(self, language: str | None) -> tuple[EventPattern, ...]:
        """The patterns that apply to a document of ``language`` (None: all)."""
        if language is None:
            return self.patterns
        return tuple(pattern for pattern in self.patterns if pattern.lang == language)

    def matching(self, sentence: str, language: str | None) -> list[EventPattern]:
        """The patterns of ``language`` that match ``sentence`` (a stored sentence), in file
        order."""
        tokens = sentence_tokens(sentence)
        return [pattern for pattern in self.for_language(language) if pattern.matches(tokens)]

    def unknown_event_types(self, codes: Collection[str]) -> list[str]:
        """The event types the patterns use that are not in ``codes`` (e.g. the active
        terms of the ``event_type`` vocabulary), sorted."""
        return sorted({pattern.event_type for pattern in self.patterns} - set(codes))


def _strings(entry: Mapping[str, Any], key: str, where: str) -> list[str]:
    value = entry.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise EventPatternsError(f"{where}: {key} must be a list of non-empty strings")
    return value


def _stem(text: str, where: str) -> str:
    folded = fold(text.strip()).removesuffix("-")
    if not _WORD.fullmatch(folded):
        raise EventPatternsError(f"{where}: the stem {text!r} must be a single word")
    return folded


def _phrase(text: str, where: str) -> tuple[PhraseWord, ...]:
    words: list[PhraseWord] = []
    for element in fold(text).split():
        if len(element) > 1 and element.endswith("-"):
            words.append((_stem(element, where), True))
        else:
            words.extend((token, False) for token in _TOKEN.findall(element))
    if not any(_WORD.fullmatch(word) for word, _ in words):
        raise EventPatternsError(f"{where}: the phrase {text!r} has no words")
    return tuple(words)


def parse_pattern(entry: Any, index: int) -> EventPattern:
    """Check and fold one entry of ``patterns``."""
    where = f"{EVENT_PATTERNS_FILE}: pattern {index + 1}"
    if not isinstance(entry, dict):
        raise EventPatternsError(f"{where}: must be a mapping")
    unknown = set(entry) - _KEYS
    if unknown:
        raise EventPatternsError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("id", "event_type", "lang"):
        value = entry.get(key)
        if not isinstance(value, str) or not _CODE.fullmatch(value):
            raise EventPatternsError(f"{where}: {key} must be a code ([a-z0-9_]+)")
    where = f"{EVENT_PATTERNS_FILE}: pattern {entry['id']}"
    stems = tuple(_stem(item, where) for item in _strings(entry, "stems", where))
    phrases = tuple(_phrase(item, where) for item in _strings(entry, "phrases", where))
    all_of = tuple(_stem(item, where) for item in _strings(entry, "all_of", where))
    if not (stems or phrases or all_of):
        raise EventPatternsError(f"{where}: needs stems, phrases or all_of")
    if len(all_of) == 1:
        raise EventPatternsError(f"{where}: all_of needs at least two stems (else use stems)")
    return EventPattern(
        id=entry["id"],
        event_type=entry["event_type"],
        lang=entry["lang"],
        stems=stems,
        phrases=phrases,
        all_of=all_of,
    )


def parse_event_patterns(data: Any) -> EventPatterns:
    """Check the content of ``event_patterns.yaml``."""
    if not isinstance(data, dict):
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: expected a mapping")
    if "vocabulary" in data:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: must not have a vocabulary key")
    if data.get("version") != FILE_VERSION:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: version must be {FILE_VERSION}")
    entries = data.get("patterns")
    if not isinstance(entries, list) or not entries:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: patterns must be a non-empty list")
    patterns = tuple(parse_pattern(entry, index) for index, entry in enumerate(entries))
    ids = [pattern.id for pattern in patterns]
    duplicates = sorted({pattern_id for pattern_id in ids if ids.count(pattern_id) > 1})
    if duplicates:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: duplicate ids {duplicates}")
    return EventPatterns(patterns)


@lru_cache(maxsize=4)
def _load_cached(path: str, _mtime_ns: int, _size: int) -> EventPatterns:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE}: invalid YAML") from exc
    return parse_event_patterns(data)


def load_event_patterns(codebook_dir: Path) -> EventPatterns:
    """Read and check ``<codebook_dir>/event_patterns.yaml`` (cached while unchanged)."""
    path = codebook_dir / EVENT_PATTERNS_FILE
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise EventPatternsError(f"{EVENT_PATTERNS_FILE} is missing") from exc
    return _load_cached(str(path), stat.st_mtime_ns, stat.st_size)
