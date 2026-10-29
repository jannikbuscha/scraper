"""Text normalisation for search, folding and sorting (docs/DATA_MODEL.md §10).

:func:`normalize_for_search` is applied to indexed text and to queries alike, so that
apostrophe, space and dash variants match each other. :func:`fold` is registered as the
SQL function ``mdt_fold`` and :func:`sortkey` as ``mdt_sortkey`` on every connection.
"""

from __future__ import annotations

import unicodedata

#: The canonical apostrophe (U+02BC MODIFIER LETTER APOSTROPHE). Unlike U+2019 it is a
#: letter, so FTS5's unicode61 tokenizer keeps words such as ``зʼявилася`` in one token.
APOSTROPHE = "\u02bc"

_APOSTROPHE_VARIANTS = (
    "'",  # U+0027 apostrophe
    "\u2019",  # right single quotation mark
    "\u2018",  # left single quotation mark
    "`",  # U+0060 grave accent
    "\u00b4",  # acute accent
    "\u02b9",  # modifier letter prime
    "\u02bc",  # modifier letter apostrophe (canonical)
)

_DASH_VARIANTS = (
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign
    "\u2e3a",  # two-em dash
    "\u2e3b",  # three-em dash
    "\ufe58",  # small em dash
    "\ufe63",  # small hyphen-minus
    "\uff0d",  # fullwidth hyphen-minus
)

SOFT_HYPHEN = "\u00ad"

#: Every space separator (Unicode category Zs) except U+0020; a test checks completeness.
UNICODE_SPACES = (
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u202f\u205f\u3000"
)


def _build_table() -> dict[int, str | None]:
    table: dict[int, str | None] = {ord(ch): APOSTROPHE for ch in _APOSTROPHE_VARIANTS}
    table.update({ord(ch): "-" for ch in _DASH_VARIANTS})
    table.update({ord(ch): " " for ch in UNICODE_SPACES})
    table[ord(SOFT_HYPHEN)] = None
    return table


_TABLE = _build_table()

# The 33 letters of the Ukrainian alphabet in alphabetical order.
UKRAINIAN_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_SORT_TABLE = {ord(letter): chr(0xE000 + index) for index, letter in enumerate(UKRAINIAN_ALPHABET)}


def normalize_for_search(value: str) -> str:
    """NFC; unify apostrophes to U+02BC, Unicode spaces to a space and dashes to ``-``;
    drop soft hyphens."""
    return unicodedata.normalize("NFC", value).translate(_TABLE)


def fold(value: str) -> str:
    """Case-insensitive comparison key: ``normalize_for_search(value).casefold()``."""
    return normalize_for_search(value).casefold()


def sortkey(value: str) -> str:
    """Sort key: :func:`fold` with Ukrainian letters mapped to U+E000.. in alphabet order.

    Ukrainian text therefore sorts alphabetically (ґ after г, є after е, і/ї after и)
    and after Latin text.
    """
    return fold(value).translate(_SORT_TABLE)


def sql_fold(value: object) -> str | None:
    """SQL function ``mdt_fold``: NULL stays NULL; other values are folded as text."""
    if value is None:
        return None
    return fold(value if isinstance(value, str) else str(value))


def sql_sortkey(value: object) -> str | None:
    """SQL function ``mdt_sortkey``: NULL stays NULL; other values as text."""
    if value is None:
        return None
    return sortkey(value if isinstance(value, str) else str(value))
