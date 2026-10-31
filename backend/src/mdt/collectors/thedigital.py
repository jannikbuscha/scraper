"""Shared helpers of the two thedigital.gov.ua collectors, C1 ``ministry_projects`` and C4
``ministry_news`` (docs/COLLECTORS.md §8.1, §8.4; SOURCES S1, S4).

* the site's URLs and constants;
* the loader data embedded in a stored page (:func:`loader_entry`, docs/COLLECTORS.md §7.2)
  and the licence statement of a page (:func:`page_licence`, §7.4);
* small value helpers (evidence of a snapshot, publication dates, joined texts, slugs);
* the run values both collectors' page parsers need (:class:`SiteValues`);
* :func:`fetch_parsed`: one request, its parse and the run messages of both;
  :class:`Pagination`: the pages of a listing while it is read.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from mdt.collectors.base import Evidence, RunContext, Snapshot, focal_org_id
from mdt.collectors.parsing import ParseError, ParseResult
from mdt.collectors.parsing.dates import SourceDate, from_iso_offset
from mdt.collectors.parsing.html_text import decode_html, read_page
from mdt.collectors.parsing.texts import normalize_document_text
from mdt.collectors.parsing.turbostream import find_route, loader_data

HOST = "thedigital.gov.ua"
SITE = f"https://{HOST}"
#: ``publisher`` of the documents read from the site's own pages.
PUBLISHER = HOST
#: ``extraction_method`` of texts read from the embedded loader data.
TURBO_STREAM = "turbo-stream"
#: Statuses a parser reports as ``not_found`` (docs/COLLECTORS.md §7.1).
NOT_FOUND_STATUSES = frozenset({404, 410})


def evidence_of(snapshot: Snapshot) -> Evidence:
    """The evidence of a candidate read from ``snapshot`` (where the page was read)."""
    return Evidence(
        raw_snapshot_id=snapshot.raw_snapshot_id,
        source_url=snapshot.final_url or snapshot.url or "",
    )


def loader_entry(
    snapshot: Snapshot, any_of: Iterable[str], *, required: Iterable[str] = ()
) -> dict[str, Any]:
    """The loader entry of a stored page (or ``.data`` body) with the given keys, picked by
    its keys, never by its route ID. Raises :class:`ParseError`."""
    decoded = decode_html(snapshot.body, snapshot.headers.get("content-type"))
    return find_route(loader_data(decoded.text), any_of, required=required)[1]


def page_licence(
    snapshot: Snapshot, default: str | None
) -> tuple[str | None, list[tuple[str, str]]]:
    """The licence code of a page from its statements (CC BY 4.0 or all rights reserved,
    docs/COLLECTORS.md §7.4), else ``default``; and the warnings of decoding the page."""
    page = read_page(snapshot)
    return page.licence or default, list(page.warnings)


def mapping_of(value: Any, where: str) -> dict[str, Any]:
    """``value`` as an object; raises :class:`ParseError` naming ``where`` otherwise."""
    if not isinstance(value, dict):
        raise ParseError(f"{where} is not an object")
    return value


def list_of(value: Any, where: str) -> list[Any]:
    """``value`` as a list; raises :class:`ParseError` naming ``where`` otherwise."""
    if not isinstance(value, list):
        raise ParseError(f"{where} is not a list")
    return value


def text_of(value: Any, where: str) -> str:
    """A non-empty string (NFC, trimmed); raises :class:`ParseError` naming ``where``
    otherwise. The site writes some letters decomposed (U+0457 as U+0456 U+0308)."""
    text = optional_text(value)
    if text is None:
        raise ParseError(f"{where} is missing")
    return text


def optional_text(value: Any) -> str | None:
    """A string in NFC, trimmed, or None for anything else (or an empty string)."""
    return (unicodedata.normalize("NFC", value).strip() or None) if isinstance(value, str) else None


def last_segment(slug: str) -> str:
    """The last path segment of a site slug (``technologies/brave1`` → ``brave1``)."""
    return slug.strip("/").rsplit("/", 1)[-1]


def joined_text(*parts: str | None) -> str | None:
    """Text parts joined as paragraphs and normalised as a document text (DATA_MODEL
    §15.6); None when nothing is left."""
    text = normalize_document_text("\n\n".join(part for part in parts if part))
    return text or None


def published_of(value: Any) -> SourceDate | None:
    """The date of a ``publishedAt.iso8601`` value (ISO 8601 with offset): the
    Europe/Kyiv calendar date and the UTC timestamp; None for anything else."""
    return from_iso_offset(value) if isinstance(value, str) else None


@dataclass(frozen=True)
class SiteValues:
    """Run values the page parsers need besides a snapshot: the focal organisation (the
    ``publisher_org_id`` of the ministry's own pages) and the default licence of the
    collector (``sources.yaml``)."""

    focal_org_id: str | None
    default_licence: str | None

    @classmethod
    def of(cls, ctx: RunContext) -> SiteValues:
        """The values of the run."""
        return cls(focal_org_id(ctx), ctx.client.config.licence.code)


def fetch_parsed(
    ctx: RunContext, url: str, parse: Callable[[Snapshot], ParseResult]
) -> tuple[Snapshot, ParseResult] | None:
    """GET ``url`` and parse the response; None when the request failed (the client has
    written the run message), the response has no body or the parser raised
    :class:`ParseError` (``parse_error``). Counts ``pages_parsed`` and writes the
    parser's warnings as run messages."""
    result = ctx.client.get(url)
    if not result.ok:
        return None
    snapshot = result.snapshot
    if snapshot is None:
        ctx.message("error", "parse_error", f"{url}: the response has no body", url=url)
        return None
    try:
        parsed = parse(snapshot)
    except ParseError as exc:
        ctx.message(
            "error",
            "parse_error",
            f"{url}: {exc}",
            url=url,
            snapshot_id=snapshot.raw_snapshot_id,
        )
        return None
    ctx.count("pages_parsed")
    for code, text in parsed.warnings:
        ctx.message("warning", code, text, url=url, snapshot_id=snapshot.raw_snapshot_id)
    return snapshot, parsed


@dataclass
class Pagination:
    """The pages of one listing (``<url>``, ``<url>/page/<n>``) while it is read: the last
    page follows the newest ``pagination.lastPage``, and a total or last page that changes
    during the run gives one ``listing_changed`` warning."""

    url: str
    last_page: int = 1
    facts: tuple[int | None, int | None] | None = None
    changed: bool = False

    def page_url(self, number: int) -> str:
        """The URL of page ``number``."""
        return self.url if number == 1 else f"{self.url}/page/{number}"

    def update(self, ctx: RunContext, parsed: ParseResult, number: int) -> None:
        """Take the listing facts of page ``number``."""
        facts = (parsed.total, parsed.last_page)
        if self.facts is None:
            self.facts = facts
        elif facts != self.facts and not self.changed:
            self.changed = True
            ctx.message(
                "warning",
                "listing_changed",
                f"the listing {self.url} changed during the run: total {self.facts[0]} → "
                f"{facts[0]}, last page {self.facts[1]} → {facts[1]}",
                url=self.page_url(number),
            )
        if parsed.last_page:
            self.last_page = parsed.last_page
