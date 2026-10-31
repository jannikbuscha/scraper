# ruff: noqa: RUF002
"""Language detection without any language model (docs/COLLECTORS.md §7.5).

Over the first 5 000 letters of title and text: a Cyrillic share of at least 0.6 gives
``uk``, unless the letters ы, э, ъ, ё outnumber і, ї, є, ґ (then ``ru``); a Latin share of
at least 0.6 gives ``en``; otherwise no value. Modifier letters such as the apostrophe
U+02BC are not counted. www.kmu.gov.ua is decided by its URL instead
(:func:`kmu_language`).
"""

from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

MAX_LETTERS = 5000
MIN_SHARE = 0.6
UKRAINIAN_LETTERS = frozenset("іїєґІЇЄҐ")
RUSSIAN_LETTERS = frozenset("ыэъёЫЭЪЁ")


def _is_cyrillic(char: str) -> bool:
    return "Ѐ" <= char <= "ԯ"


def _is_latin(char: str) -> bool:
    return ("a" <= char.lower() <= "z") or ("À" <= char <= "ɏ")


def detect_language(title: str | None, text: str | None) -> str | None:
    """``uk``, ``ru``, ``en`` or None from the letters of ``title`` and ``text``."""
    letters = 0
    cyrillic = latin = ukrainian = russian = 0
    for char in f"{title or ''}\n{text or ''}":
        if not char.isalpha() or unicodedata.category(char) == "Lm":
            continue
        letters += 1
        if _is_cyrillic(char):
            cyrillic += 1
            ukrainian += char in UKRAINIAN_LETTERS
            russian += char in RUSSIAN_LETTERS
        elif _is_latin(char):
            latin += 1
        if letters >= MAX_LETTERS:
            break
    if not letters:
        return None
    if cyrillic / letters >= MIN_SHARE:
        return "ru" if russian > ukrainian else "uk"
    if latin / letters >= MIN_SHARE:
        return "en"
    return None


def kmu_language(url: str) -> str:
    """www.kmu.gov.ua: a path starting with ``/en/`` is English, anything else Ukrainian."""
    return "en" if urlsplit(url).path.startswith("/en/") else "uk"
