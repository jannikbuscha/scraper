"""Parsers and shared parsing helpers (docs/COLLECTORS.md §7).

A parser is a pure function ``parse_<page kind>(snapshot) -> ParseResult``: no network, no
database, no clock (times come from the snapshot) and no randomness. It raises
:class:`ParseError` when the structure it expects is missing, so a site change fails loudly
instead of yielding empty data (risk R3); the collector records ``parse_error`` and goes on
with the other pages.

The helpers: :mod:`.turbostream` (React Router / Remix single-fetch payloads),
:mod:`.tiptap` (TipTap JSON to text and links), :mod:`.html_text` (HTML to text, titles,
licence phrases, client-rendered shells), :mod:`.sitemaps`, :mod:`.dates` (month names,
Europe/Kyiv), :mod:`.language` (language detection without an LLM) and :mod:`.texts`
(document text normalisation, sentences, snippets).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mdt.collectors.base import Candidate


class ParseError(Exception):
    """The structure a parser expects is missing (no loader data, no ``h1``, an unknown
    turbo-stream construct, …). The message says what was expected, never the body."""


@dataclass
class ParseResult:
    """What a parser read from one snapshot (docs/COLLECTORS.md §7.1).

    ``next_urls`` are the URLs to fetch next (pagination, detail pages, files) in the
    source's order; ``not_found`` marks a 404, 410 or soft 404; ``total`` and ``last_page``
    are the listing facts; ``warnings`` are ``(code, message)`` pairs for run messages.
    """

    candidates: list[Candidate] = field(default_factory=list)
    next_urls: list[str] = field(default_factory=list)
    not_found: bool = False
    total: int | None = None
    last_page: int | None = None
    warnings: list[tuple[str, str]] = field(default_factory=list)

    def warn(self, code: str, message: str) -> None:
        """Add a warning (a run message code of docs/COLLECTORS.md §6.6)."""
        self.warnings.append((code, message))
