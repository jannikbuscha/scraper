# ruff: noqa: RUF002
"""C3 ``diia_catalog``: the service catalogue of the Diia portal on diia.gov.ua
(docs/COLLECTORS.md §8.3, SOURCES S3).

Server-rendered HTML without embedded data or an API; Cloudflare is in front, so any
challenge page blocks the host (§4.7). A run requests, in this order:

1. **the listing:** the catalogue root ``/services`` (alphabetical list
   ``div.services-byletter_item a``), the sitemap index and the services sitemap(s) it
   lists (slugs and ``lastmod``). It is complete when the list and every services sitemap
   were parsed;
2. **the categories:** the two audience pages (subcategory tiles) and every subcategory
   page they link (service links ``a.service-acc_item-service``);
3. **the services:** one page per slug, sorted by slug. Discovery is the catalogue list ∪
   the sitemap (``/services/RD4U`` appears only in the list). Slugs keep their case, and
   every request URL is built from a slug on ``https://diia.gov.ua``, so the trailing-dot
   host variant is never requested.

A service page gives a service candidate (key ``service:<slug>``) and a document candidate
(key ``page:<slug>``) with a suggested link to the service; the service is reconciled first,
so that the link resolves through its binding. ``source_categories`` and
``source_audiences`` are aggregated over the subcategory pages, so they are part of the
candidates only when both audience pages and every subcategory page they link were parsed
in this run; otherwise the warning ``incomplete_candidate`` names the missing pages. A
listed service whose page gives no candidate is sighted, so a failed page never makes a
listed key look missing.

The parsers are pure functions of a stored snapshot (§7.1). The listing and category pages
give typed results (entries with labels and ``lastmod``, memberships), which
:class:`~mdt.collectors.parsing.ParseResult` has no place for; a service page gives a
``ParseResult`` with its two candidates.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from mdt.collectors.base import (
    Candidate,
    Evidence,
    FatalRunError,
    LinkHint,
    RunContext,
    Snapshot,
    TypeDeclaration,
)
from mdt.collectors.mappings import LabelMapping, mapping_for_run
from mdt.collectors.parsing import ParseError, ParseResult
from mdt.collectors.parsing.html_text import extract_links, html_text, read_page
from mdt.collectors.parsing.sitemaps import parse_sitemap
from mdt.collectors.parsing.texts import collapse_whitespace, normalize_document_text
from mdt.collectors.urls import UrlError, parse_fetch_url
from mdt.domain.text import fold

COLLECTOR_NAME = "diia_catalog"
HOST = "diia.gov.ua"
BASE_URL = f"https://{HOST}"
CATALOGUE_URL = f"{BASE_URL}/services"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap.xml"
#: The audience pages "Громадянам" (citizens) and "Бізнесу" (business), SOURCES S3.
AUDIENCE_URLS = (
    f"{BASE_URL}/services/categories/gromadyanam",
    f"{BASE_URL}/services/categories/biznesu",
)
#: Services are created under the project with this seed key (option ``project_seed_key``).
DEFAULT_PROJECT_SEED_KEY = "diia"
CHANNEL_MAPPING = "diia_portal_channels"
PUBLISHER = HOST
SERVICE_LINK_SNIPPET = "Service page on diia.gov.ua"
#: The label of the description in a service page's info block.
DESCRIPTION_LABEL = "Опис послуги"
#: The heading of the section whose leads name the channels.
CHANNELS_HEADING = "Як отримати послугу"
CATEGORY_FIELDS = ("source_categories", "source_audiences")

_SERVICE_PATH = re.compile(r"^/services/([^/]+)/?$")
_AUDIENCE_PATH = re.compile(r"^/services/categories/[^/]+/?$")
_SUBCATEGORY_PATH = re.compile(r"^/services/categories/([^/]+)/([^/]+)/?$")
_SERVICES_SITEMAP_PATH = re.compile(r"^/sitemap-kitsoftservicesmodelsservice-\d+\.xml$")
_NOT_A_SLUG = "categories"


# --------------------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------------------


def service_url(slug: str) -> str:
    """The page of a service, built from its slug (the slug keeps its case)."""
    return f"{BASE_URL}/services/{slug}"


def _diia_path(url: str) -> str | None:
    """The path of an absolute diia.gov.ua URL (the host normalised, so ``diia.gov.ua.``
    counts as diia.gov.ua); None for other hosts and invalid URLs."""
    try:
        target = parse_fetch_url(url)
    except UrlError:
        return None
    return target.path if target.host == HOST else None


def service_slug(url: str) -> str | None:
    """The slug of a service page URL ``https://diia.gov.ua/services/<slug>``, else None."""
    path = _diia_path(url)
    match = _SERVICE_PATH.match(path) if path is not None else None
    if match is None or match.group(1) == _NOT_A_SLUG:
        return None
    return match.group(1)


def _base(snapshot: Snapshot) -> str:
    """The URL relative links of a page resolve against."""
    return snapshot.final_url or snapshot.url or BASE_URL


def _text_of(tag: Any) -> str:
    """The collapsed text of an element ('' for a missing one)."""
    return collapse_whitespace(tag.get_text(" ")) if isinstance(tag, Tag) else ""


# --------------------------------------------------------------------------------------
# Listing and category pages
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ListedService:
    """A service of the listing: its slug, the catalogue list's label and the services
    sitemap's ``lastmod`` as written (never a date of the service, SOURCES §5 item 4)."""

    slug: str
    label: str | None = None
    lastmod: str | None = None


def parse_catalogue(snapshot: Snapshot) -> list[ListedService]:
    """The alphabetical service list of the catalogue root
    (``div.services-byletter_item a``), one entry per slug in page order."""
    page = read_page(snapshot)
    entries: dict[str, ListedService] = {}
    for link in extract_links(page.soup, _base(snapshot), "div.services-byletter_item a[href]"):
        slug = service_slug(link.href)
        if slug is not None and slug not in entries:
            entries[slug] = ListedService(slug, label=link.text or None)
    if not entries:
        raise ParseError("the catalogue root has no service list (div.services-byletter_item a)")
    return list(entries.values())


def parse_sitemap_index(snapshot: Snapshot) -> ParseResult:
    """The services sitemaps (``sitemap-kitsoftservicesmodelsservice-<n>.xml`` on
    diia.gov.ua) a sitemap index lists, as ``next_urls`` in index order."""
    urls: list[str] = []
    for entry in parse_sitemap(snapshot.body).entries:
        path = _diia_path(entry.loc)
        if path is not None and _SERVICES_SITEMAP_PATH.match(path):
            url = f"{BASE_URL}{path}"
            if url not in urls:
                urls.append(url)
    if not urls:
        raise ParseError("the sitemap index lists no services sitemap")
    return ParseResult(next_urls=urls)


def parse_services_sitemap(snapshot: Snapshot) -> list[ListedService]:
    """The service pages of a services sitemap with their ``lastmod``, one entry per slug
    in document order."""
    entries: dict[str, ListedService] = {}
    for entry in parse_sitemap(snapshot.body).entries:
        slug = service_slug(entry.loc)
        if slug is not None and slug not in entries:
            entries[slug] = ListedService(slug, lastmod=entry.lastmod)
    if not entries:
        raise ParseError("the services sitemap lists no service page")
    return list(entries.values())


def parse_audience_page(snapshot: Snapshot) -> ParseResult:
    """The subcategory pages an audience page links in its tiles (``div.services_item``),
    as ``next_urls`` in page order. Links inside a tile's description are no tiles."""
    page = read_page(snapshot)
    urls: list[str] = []
    for link in extract_links(page.soup, _base(snapshot), "div.services_item a[href]"):
        path = _diia_path(link.href)
        match = _SUBCATEGORY_PATH.match(path) if path is not None else None
        if match is not None:
            url = f"{BASE_URL}/services/categories/{match.group(1)}/{match.group(2)}"
            if url not in urls:
                urls.append(url)
    if not urls:
        raise ParseError("the audience page has no subcategory tiles (div.services_item)")
    return ParseResult(next_urls=urls)


@dataclass(frozen=True)
class Subcategory:
    """A subcategory page: its URL, the audience label of its breadcrumb, its label
    ``<audience> / <subcategory>``, the services it lists and its snapshot."""

    url: str
    audience: str
    label: str
    slugs: tuple[str, ...]
    snapshot_id: str


def parse_subcategory_page(snapshot: Snapshot) -> Subcategory:
    """A subcategory page: the audience label from the breadcrumb link to its audience
    page, the subcategory label from the ``h1`` and the listed services
    (``a.service-acc_item-service``, deduplicated by slug). The "Від А до Я" accordion
    repeats the services with other markup and is not read."""
    page = read_page(snapshot)
    base = _base(snapshot)
    audience = None
    for link in extract_links(page.soup, base, "ul.breadcrumb a[href]"):
        path = _diia_path(link.href)
        if path is not None and _AUDIENCE_PATH.match(path) and link.text:
            audience = link.text
    if audience is None:
        raise ParseError("the subcategory page has no breadcrumb link to its audience page")
    label = _text_of(page.soup.find("h1"))
    if not label:
        raise ParseError("the subcategory page has no h1")
    slugs: list[str] = []
    for link in extract_links(page.soup, base, "a.service-acc_item-service[href]"):
        slug = service_slug(link.href)
        if slug is not None and slug not in slugs:
            slugs.append(slug)
    if not slugs and not _empty_subcategory(page.soup):
        raise ParseError("the subcategory page lists no service (a.service-acc_item-service)")
    return Subcategory(
        url=snapshot.url or base,
        audience=audience,
        label=f"{audience} / {label}",
        slugs=tuple(slugs),
        snapshot_id=snapshot.raw_snapshot_id,
    )


def _empty_subcategory(soup: BeautifulSoup) -> bool:
    """A subcategory without services: its service section is there, but the link boxes of
    the "Від А до Я" accordion hold no link (two such pages on 2026-10-30, live check). A
    page whose boxes hold links that are not read as services has changed its markup."""
    boxes = soup.select("section.service-acc_section .service-acc_item-link-box")
    return bool(boxes) and not any(box.find("a", href=True) for box in boxes)


# --------------------------------------------------------------------------------------
# Service pages
# --------------------------------------------------------------------------------------


def redirect_target(snapshot: Snapshot) -> str | None:
    """The target of a page that only redirects with ``<meta http-equiv="refresh">`` and
    has no service title, or None. ``/services/RD4U`` (listed in the catalogue) answered so
    on 2026-10-30 with HTTP 200, pointing to the subcategory of the Register of Damage."""
    page = read_page(snapshot)
    if page.soup.select_one("h1.service-type_title") is not None:
        return None
    for meta in page.soup.find_all("meta"):
        if str(meta.get("http-equiv", "")).strip().lower() != "refresh":
            continue
        _delay, _, target = str(meta.get("content", "")).partition("=")
        target = target.strip().strip("'\"")
        if target:
            return target
    return None


def heading_key(text: str) -> str:
    """The comparison form of a heading or label: folded (apostrophe variants agree),
    whitespace collapsed, a trailing colon dropped, and the conjunction "й" read as "та"
    (so "Пов’язані закони й накази" equals "Пов'язані закони та накази")."""
    words = collapse_whitespace(fold(text)).rstrip(":").split()
    return " ".join("та" if word == "й" else word for word in words)


@dataclass(frozen=True)
class ServicePage:
    """What a service page states."""

    title: str  # h1.service-type_title (the meta title can differ, SOURCES S3)
    description: str | None  # the value of "Опис послуги"
    channel_leads: tuple[str, ...] | None  # under "Як отримати послугу"; None: no such section
    text: str  # the main content: h1, label/value pairs, the section.service-acc_section blocks
    licence: str | None  # from the page's statements (§7.4)
    warnings: tuple[tuple[str, str], ...] = ()  # of decoding (``invalid_value``)


def read_service_page(snapshot: Snapshot) -> ServicePage:
    """Read a service page (raises ParseError without ``h1.service-type_title``)."""
    page = read_page(snapshot)
    title = _text_of(page.soup.select_one("h1.service-type_title"))
    if not title:
        raise ParseError("the service page has no h1.service-type_title")
    pairs = _info_pairs(page.soup)
    wanted = heading_key(DESCRIPTION_LABEL)
    description = next((value for label, value in pairs if heading_key(label) == wanted), None)
    sections = page.soup.select("section.service-acc_section")
    lines = [title, *(f"{label} {value}" for label, value in pairs)]
    lines.extend(html_text(section) for section in sections)
    return ServicePage(
        title=title,
        description=description,
        channel_leads=_channel_leads(sections),
        text=normalize_document_text("\n".join(line for line in lines if line)),
        licence=page.licence,
        warnings=page.warnings,
    )


def _info_pairs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """The label/value pairs of the info block (``.service-info_first-item`` and
    ``.service-info_second-item``) in page order, values as text."""
    pairs: list[tuple[str, str]] = []
    for item in soup.select(".service-info_first-item, .service-info_second-item"):
        label = _text_of(item.select_one(".service-info_first-label, .service-info_second-label"))
        value_tag = item.select_one(".service-info_first-text, .service-info_second-text")
        value = html_text(value_tag) if value_tag is not None else ""
        if label and value:
            pairs.append((label, value))
    return pairs


def _channel_leads(sections: Iterable[Tag]) -> tuple[str, ...] | None:
    """The leads (``.service-acc_simple-lead``) of the section headed "Як отримати
    послугу", in page order; None if the page has no such section."""
    wanted = heading_key(CHANNELS_HEADING)
    for section in sections:
        if heading_key(_text_of(section.find("h2"))) == wanted:
            leads = (_text_of(lead) for lead in section.select(".service-acc_simple-lead"))
            return tuple(lead for lead in leads if lead)
    return None


@dataclass(frozen=True)
class CatalogContext:
    """What the candidates of a service page need besides the page."""

    project_id: str | None  # the project of the services this run creates
    channels: LabelMapping  # diia_portal_channels (§7.9)
    channel_order: Mapping[str, int]  # channel code -> position in its vocabulary
    default_licence: str
    listed: Mapping[str, ListedService]
    categories: Mapping[str, Sequence[Subcategory]] | None  # None: memberships incomplete


def parse_service_page(snapshot: Snapshot, slug: str, context: CatalogContext) -> ParseResult:
    """The service candidate and the document candidate of a service page, in this order;
    unmapped channel leads give the warning ``unmapped_label``. A page that only redirects
    elsewhere (:func:`redirect_target`) gives no candidate and the warning
    ``unsupported_content``."""
    url = service_url(slug)
    target = redirect_target(snapshot)
    if target is not None:
        message = f"{url}: not a service page; it redirects to {target}"
        return ParseResult(warnings=[("unsupported_content", message)])
    page = read_service_page(snapshot)
    result = ParseResult(warnings=[(code, f"{url}: {message}") for code, message in page.warnings])
    evidence = Evidence(
        raw_snapshot_id=snapshot.raw_snapshot_id, source_url=snapshot.final_url or url
    )
    fields: dict[str, Any] = {"name_uk": page.title, "urls": [url]}
    if context.project_id is not None:
        fields["project_id"] = context.project_id
    if page.description:
        fields["description_uk"] = page.description
    if page.channel_leads is not None:
        channels = _channel_codes(page.channel_leads, context, result, url)
        if channels:
            fields["channels"] = channels
    field_snapshots: dict[str, list[str]] = {}
    memberships = sorted(
        (context.categories or {}).get(slug, ()), key=lambda subcategory: subcategory.url
    )
    if memberships:
        fields["source_categories"] = [
            {"source": COLLECTOR_NAME, "label": item.label, "url": item.url} for item in memberships
        ]
        fields["source_audiences"] = sorted({item.audience for item in memberships})
        pages = list(dict.fromkeys(item.snapshot_id for item in memberships))
        field_snapshots = {name: list(pages) for name in CATEGORY_FIELDS}
    listed = context.listed.get(slug)
    result.candidates.append(
        Candidate(
            entity_type="service",
            key=f"service:{slug}",
            evidence=evidence,
            label=page.title,
            url=url,
            external_id=slug,
            fields=fields,
            field_snapshots=field_snapshots,
            details={"lastmod": listed.lastmod if listed is not None else None},
        )
    )
    result.candidates.append(
        Candidate(
            entity_type="document",
            key=f"page:{slug}",
            evidence=evidence,
            label=page.title,
            url=url,
            external_id=slug,
            fields={
                "title": page.title,
                "url": url,
                "publisher": PUBLISHER,
                "doc_type": "project_page",
                "language": "uk",
                "license": page.licence or context.default_licence,
            },
            text=page.text,
            text_snapshot_id=snapshot.raw_snapshot_id,
            extraction_method="selector",
            links=[LinkHint(snippet=SERVICE_LINK_SNIPPET, subject_key=f"service:{slug}")],
        )
    )
    return result


def _channel_codes(
    leads: Sequence[str], context: CatalogContext, result: ParseResult, url: str
) -> list[str]:
    """The channel codes of the leads, in vocabulary order; a lead without a mapping is
    skipped with the warning ``unmapped_label`` ("Результат" is ignored silently)."""
    codes: list[str] = []
    for lead in leads:
        found = context.channels.lookup(lead)
        if found.status in ("unmapped", "fallback"):
            result.warn(
                "unmapped_label",
                f"{url}: the channel lead {lead!r} has no code in {CHANNEL_MAPPING}",
            )
        if found.code is not None and found.code not in codes:
            codes.append(found.code)
    last = len(context.channel_order)
    return sorted(codes, key=lambda code: (context.channel_order.get(code, last), code))


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


SERVICE_DECLARATION = TypeDeclaration(
    creates=True,
    writes=frozenset(
        {
            "project_id",
            "name_uk",
            "description_uk",
            "urls",
            "channels",
            "source_categories",
            "source_audiences",
        }
    ),
    match_rules=("external_id", "url_fields"),
    discontinued=True,
)
DOCUMENT_DECLARATION = TypeDeclaration(
    creates=True,
    writes=frozenset({"title", "url", "publisher", "doc_type", "language", "license"}),
    match_rules=("document",),
)


@dataclass(frozen=True)
class _Listing:
    """The services of the listing by slug, and whether every listing unit was parsed."""

    entries: Mapping[str, ListedService]
    complete: bool


class DiiaCatalogCollector:
    """C3 ``diia_catalog`` (see the module docstring). Modes make no difference; ``limit``
    caps the number of service pages."""

    NAME = COLLECTOR_NAME
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {
        "service": SERVICE_DECLARATION,
        "document": DOCUMENT_DECLARATION,
    }
    MODES: tuple[str, ...] = ()
    PARAMS: frozenset[str] = frozenset({"limit"})

    def run(self, ctx: RunContext) -> None:
        """Read the listing and the categories, then every service page by slug."""
        project_id = _project_of_services(ctx)
        mapping = mapping_for_run(ctx, CHANNEL_MAPPING)
        listing = _read_listing(ctx)
        if listing.complete:
            ctx.client.listing_done()  # later failures of the host only make the run partial
        context = CatalogContext(
            project_id=project_id,
            channels=mapping,
            channel_order=_vocabulary_order(ctx, mapping.vocabulary),
            default_licence=ctx.client.config.licence.code,
            listed=listing.entries,
            categories=_read_categories(ctx),
        )
        for slug in sorted(listing.entries)[: ctx.params.get("limit")]:
            if ctx.cancelled():
                return
            _collect_service(ctx, slug, context)
        if listing.complete:  # only now: a failed run must not mark unvisited keys missing
            ctx.listing_complete()


def _project_of_services(ctx: RunContext) -> str:
    """The live project whose ``seed_key`` is option ``project_seed_key``; the run fails
    without one, because no service could be created (docs/COLLECTORS.md §8.3)."""
    seed_key = ctx.options.get("project_seed_key", DEFAULT_PROJECT_SEED_KEY)
    if not isinstance(seed_key, str) or not seed_key:
        raise FatalRunError("option project_seed_key must be a project seed key")
    for record in ctx.live_records("project", ["seed_key"]):
        if record["seed_key"] == seed_key:
            return str(record["id"])
    raise FatalRunError(
        f"no live project has the seed key {seed_key!r} (option project_seed_key), "
        "so services cannot be created"
    )


def _vocabulary_order(ctx: RunContext, vocabulary: str) -> dict[str, int]:
    """Position of each code of ``vocabulary`` by ``sort_order``, then code."""
    terms = [
        term
        for term in ctx.live_records("vocabulary_term", ["vocabulary", "code", "sort_order"])
        if term["vocabulary"] == vocabulary
    ]
    terms.sort(key=lambda term: (term["sort_order"] is None, term["sort_order"] or 0, term["code"]))
    return {str(term["code"]): position for position, term in enumerate(terms)}


def _read_listing(ctx: RunContext) -> _Listing:
    """The catalogue list and the services sitemaps (complete when all were parsed)."""
    entries: dict[str, ListedService] = {}
    catalogue = _fetch_and_parse(ctx, CATALOGUE_URL, parse_catalogue)
    for entry in catalogue or ():
        entries[entry.slug] = entry
    index = _fetch_and_parse(ctx, SITEMAP_INDEX_URL, parse_sitemap_index)
    complete = catalogue is not None and index is not None
    for url in index.next_urls if index is not None else ():
        listed = _fetch_and_parse(ctx, url, parse_services_sitemap)
        if listed is None:
            complete = False
            continue
        for entry in listed:
            known = entries.get(entry.slug)
            label = known.label if known is not None else None
            entries[entry.slug] = ListedService(entry.slug, label, entry.lastmod)
    return _Listing(entries, complete)


def _read_categories(ctx: RunContext) -> dict[str, list[Subcategory]] | None:
    """The subcategory pages listing each service (by slug); None, with the warning
    ``incomplete_candidate``, unless both audience pages and every subcategory page they
    link were parsed."""
    missing: list[str] = []
    pages: list[str] = []
    for url in AUDIENCE_URLS:
        tiles = _fetch_and_parse(ctx, url, parse_audience_page)
        if tiles is None:
            missing.append(url)
            continue
        for page in tiles.next_urls:
            if page not in pages:
                pages.append(page)
    memberships: dict[str, list[Subcategory]] = {}
    for url in pages:
        subcategory = _fetch_and_parse(ctx, url, parse_subcategory_page)
        if subcategory is None:
            missing.append(url)
            continue
        for slug in subcategory.slugs:
            memberships.setdefault(slug, []).append(subcategory)
    if missing:
        ctx.message(
            "warning",
            "incomplete_candidate",
            f"source_categories and source_audiences are left out of every service "
            f"candidate: {len(missing)} category page(s) could not be read: " + ", ".join(missing),
            details={"fields": list(CATEGORY_FIELDS), "missing": missing},
        )
        return None
    return memberships


def _collect_service(ctx: RunContext, slug: str, context: CatalogContext) -> None:
    """Fetch, parse and reconcile one service page (the service first, then its page);
    a page that gives no candidate is sighted instead."""
    snapshot = _fetch(ctx, service_url(slug))
    result = None
    if snapshot is not None:
        result = _parse(ctx, snapshot, lambda page: parse_service_page(page, slug, context))
    if snapshot is not None and result is not None:
        for code, text in result.warnings:
            ctx.message(
                "warning", code, text, url=snapshot.url, snapshot_id=snapshot.raw_snapshot_id
            )
    if result is None or not result.candidates:
        _sight_service(ctx, slug, context)
        return
    for candidate in result.candidates:
        ctx.reconcile(candidate)


def _sight_service(ctx: RunContext, slug: str, context: CatalogContext) -> None:
    """A listed service whose page gave no candidate: both of its keys stay seen
    (docs/DATA_MODEL.md §15.7: a failed detail page cannot hide a key)."""
    listed = context.listed.get(slug)
    label = listed.label if listed is not None else None
    url = service_url(slug)
    details = {"lastmod": listed.lastmod if listed is not None else None}
    ctx.observe("service", f"service:{slug}", url=url, label=label, details=details)
    ctx.observe("document", f"page:{slug}", url=url, label=label)


def _fetch(ctx: RunContext, url: str) -> Snapshot | None:
    """The stored response of a successful GET, or None. The client has written the run
    message of a failed request; an empty body is a ``parse_error``."""
    result = ctx.client.get(url)
    if not result.ok:
        return None
    if result.snapshot is None:
        ctx.message("error", "parse_error", f"{url}: the response has no body", url=url)
        return None
    return result.snapshot


def _parse[T](ctx: RunContext, snapshot: Snapshot, parser: Callable[[Snapshot], T]) -> T | None:
    """Run a parser; a :class:`ParseError` becomes the run message ``parse_error``."""
    try:
        parsed = parser(snapshot)
    except ParseError as exc:
        ctx.message(
            "error",
            "parse_error",
            f"{snapshot.url}: {exc}",
            url=snapshot.url,
            snapshot_id=snapshot.raw_snapshot_id,
        )
        return None
    ctx.count("pages_parsed")
    return parsed


def _fetch_and_parse[T](ctx: RunContext, url: str, parser: Callable[[Snapshot], T]) -> T | None:
    """:func:`_fetch` and :func:`_parse`; None if either failed."""
    snapshot = _fetch(ctx, url)
    return _parse(ctx, snapshot, parser) if snapshot is not None else None


COLLECTOR = DiiaCatalogCollector()
