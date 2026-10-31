"""Text helpers shared by the parsers, the tagger and text extraction.

* :func:`normalize_document_text` and :func:`text_hash`: the normalisation and hash of a
  document's text version (docs/DATA_MODEL.md §15.6);
* :func:`collapse_whitespace`, :func:`snippet` and :func:`clip_quote` for labels, link
  snippets and evidence quotes;
* :func:`sentence_spans`: the sentences of a stored text for the event patterns
  (docs/COLLECTORS.md §7.7), as offsets into that text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from mdt.collectors.base import MAX_QUOTE_CHARS

#: C0 control characters except tab (0x09) and line feed (0x0A).
_C0_EXCEPT_TAB_LF = re.compile(r"[\x00-\x08\x0b-\x1f]")
_TRAILING_SPACE = re.compile(r"[^\S\n]+$", re.MULTILINE)
_MANY_LINE_BREAKS = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s+")
#: A sentence ends at a line break, or after ``.``, ``!``, ``?`` or ``…`` (also several, as
#: in ``?!``) that whitespace follows; a dot inside a name such as ``Дія.City`` is followed
#: by a letter and does not end a sentence.
_SENTENCE_END = re.compile(r"\n|[.!?…]+(?=\s)")


def normalize_document_text(text: str) -> str:
    """The stored form of an extracted text (DATA_MODEL §15.6): NFC; CRLF and CR to LF;
    C0 control characters except tab and newline removed; trailing whitespace removed per
    line; runs of three or more line breaks reduced to two; trimmed."""
    result = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    result = _C0_EXCEPT_TAB_LF.sub("", result)
    result = _TRAILING_SPACE.sub("", result)
    result = _MANY_LINE_BREAKS.sub("\n\n", result)
    return result.strip()


def text_hash(normalized: str) -> str:
    """``text_hash``: SHA-256 (hex) of the UTF-8 bytes of a normalised text."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def collapse_whitespace(value: str) -> str:
    """Every run of whitespace (Unicode spaces and line breaks included) becomes one
    space; the result is trimmed."""
    return _WHITESPACE.sub(" ", value).strip()


def snippet(text: str, start: int, end: int, context: int = 120) -> str:
    """Up to ``context`` characters before and after ``text[start:end]``, whitespace
    collapsed (the snippet of a suggested document link, docs/COLLECTORS.md §7.6)."""
    return collapse_whitespace(text[max(0, start - context) : end + context])


def clip_quote(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    """A verbatim quote cut to at most ``limit`` characters (no ellipsis is added, so the
    quote stays a substring of its source)."""
    return text[:limit]


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """The sentences of ``text`` as ``(start, end)`` offsets, without surrounding
    whitespace; empty sentences are skipped. Sentences end at line breaks and after
    ``.``, ``!``, ``?`` or ``…`` followed by whitespace (docs/COLLECTORS.md §7.7)."""
    spans: list[tuple[int, int]] = []
    position = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.start() if match.group() == "\n" else match.end()
        _append_span(spans, text, position, end)
        position = match.end()
    _append_span(spans, text, position, len(text))
    return spans


def _append_span(spans: list[tuple[int, int]], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end))
