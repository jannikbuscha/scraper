"""C2 ``project_sites``: the official URLs of the projects, generic pass
(docs/COLLECTORS.md §8.2, SOURCES S2).

**Input:** the ``official_urls`` of all live projects at run start, minus the excluded hosts
(``sources.yaml``), one entry per canonical URL with every project that lists it, in
canonical-URL order. One GET per URL (home pages; no link following, no sitemap inventory in
Phase 2); redirects to other hosts are followed by the client (§4.5). There is no listing
host: every URL is its own unit, so a blocked host makes the run partial, never failed.

**Candidates:** one document per URL (key ``url:<canonical URL>``) with the generic page text
(§7.4), ``title`` = the first ``h1`` else ``<title>``, ``doc_type = project_page``,
``publisher`` = the host of the final URL, ``language`` by §7.5, ``license`` from the page's
statements (default from ``sources.yaml``), ``extraction_method = html`` and no publication
date, plus a suggested link to every project whose ``official_urls`` contain the URL.

**Observed only**, with a warning: a client-rendered shell (``no_server_rendered_content``),
a page whose title or ``h1`` matches a ``soft_404_patterns`` phrase of its host
(``soft_404``) and a response that is not HTML (``unsupported_content``). Every input URL
without a document is sighted, so it is never reported missing while a project lists it.

**Complete listing:** every input URL got a final response (any status).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from bs4.element import Tag

from mdt.collectors.base import (
    MAX_KEY_CHARS,
    Candidate,
    Evidence,
    FatalRunError,
    LinkHint,
    RunContext,
    Snapshot,
    TypeDeclaration,
)
from mdt.collectors.parsing import ParseResult
from mdt.collectors.parsing.html_text import HtmlPage, read_page
from mdt.collectors.parsing.language import detect_language
from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.collectors.store import media_type
from mdt.collectors.urls import UrlError, normalize_host, parse_fetch_url
from mdt.domain.text import fold
from mdt.domain.urls import canonical_url

COLLECTOR_NAME = "project_sites"
OFFICIAL_URL_SNIPPET = "Official URL of the project"
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})


@dataclass(frozen=True)
class SiteUrl:
    """An input URL: as a project lists it, its observation key and the projects (IDs)
    whose ``official_urls`` contain it."""

    url: str
    key: str
    project_ids: tuple[str, ...]


def official_sites(
    projects: Iterable[Mapping[str, Any]], exclude_hosts: Collection[str]
) -> list[SiteUrl]:
    """The input URLs: every official URL of ``projects`` (``{id, official_urls}``) whose
    host is not excluded, one per canonical URL (the first spelling found is requested),
    sorted by canonical URL. Invalid URLs are skipped."""
    found: dict[str, tuple[str, list[str]]] = {}
    for project in projects:
        for url in project.get("official_urls") or []:
            try:
                host = parse_fetch_url(url).host
                canonical = canonical_url(url)
            except UrlError:
                continue
            if host in exclude_hosts:
                continue
            _, project_ids = found.setdefault(canonical, (url, []))
            project_id = str(project["id"])
            if project_id not in project_ids:
                project_ids.append(project_id)
    return [
        SiteUrl(url=url, key=f"url:{canonical}", project_ids=tuple(sorted(project_ids)))
        for canonical, (url, project_ids) in sorted(found.items())
    ]


def soft_404_patterns(options: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Option ``soft_404_patterns``: normalised host -> literal phrases. A malformed option
    fails the run."""
    raw = options.get("soft_404_patterns") or {}
    problem = "option soft_404_patterns must map host names to lists of phrases"
    if not isinstance(raw, Mapping):
        raise FatalRunError(problem)
    patterns: dict[str, tuple[str, ...]] = {}
    for host, phrases in raw.items():
        if not isinstance(host, str) or not isinstance(phrases, list):
            raise FatalRunError(problem)
        if not all(isinstance(phrase, str) and phrase.strip() for phrase in phrases):
            raise FatalRunError(problem)
        try:
            patterns[normalize_host(host)] = tuple(phrase.strip() for phrase in phrases)
        except UrlError as exc:
            raise FatalRunError(f"{problem}: {host!r} is not a host name") from exc
    return patterns


# --------------------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------------------


def is_html(snapshot: Snapshot) -> bool:
    """An HTML response by its ``Content-Type`` (without one: a body starting with ``<``)."""
    kind = snapshot.content_type or media_type(snapshot.headers.get("content-type"))
    if kind is not None:
        return kind in HTML_TYPES
    return snapshot.body.lstrip()[:1] == b"<"


def soft_404_phrase(page: HtmlPage, phrases: Sequence[str]) -> str | None:
    """The first phrase that occurs (case-folded) in the page's ``<title>`` or first
    ``h1``, else None."""
    texts = []
    for name in ("title", "h1"):
        tag = page.soup.find(name)
        if isinstance(tag, Tag):
            texts.append(fold(collapse_whitespace(tag.get_text(" "))))
    for phrase in phrases:
        if any(fold(phrase) in text for text in texts):
            return phrase
    return None


def parse_site_page(
    snapshot: Snapshot,
    site: SiteUrl,
    *,
    soft_404_patterns: Mapping[str, Sequence[str]],
    default_licence: str,
) -> ParseResult:
    """The document candidate of an official URL's page, or none (with a warning) for a
    response that is not HTML, a client-rendered shell or a soft 404 (``not_found``)."""
    final_url = snapshot.final_url or snapshot.url or site.url
    result = ParseResult()
    if not is_html(snapshot):
        kind = snapshot.content_type or snapshot.headers.get("content-type") or "no content type"
        result.warn("unsupported_content", f"{final_url}: not an HTML page ({kind}); no document")
        return result
    page = read_page(snapshot)
    for code, message in page.warnings:
        result.warn(code, f"{final_url}: {message}")
    if page.client_shell:
        result.warn(
            "no_server_rendered_content",
            f"{final_url}: client-rendered page with {len(page.text)} characters of "
            "server-rendered text; no document",
        )
        return result
    host = parse_fetch_url(final_url).host
    phrase = soft_404_phrase(page, soft_404_patterns.get(host, ()))
    if phrase is not None:
        result.not_found = True
        result.warn("soft_404", f"{final_url}: the page says {phrase!r} (soft 404); no document")
        return result
    fields: dict[str, Any] = {
        "url": final_url,
        "publisher": host,
        "doc_type": "project_page",
        "license": page.licence or default_licence,
    }
    if page.title:
        fields["title"] = page.title
    language = detect_language(page.title, page.text)
    if language is not None:
        fields["language"] = language
    result.candidates.append(
        Candidate(
            entity_type="document",
            key=site.key,
            evidence=Evidence(raw_snapshot_id=snapshot.raw_snapshot_id, source_url=final_url),
            label=page.title,
            url=final_url,
            fields=fields,
            text=page.text or None,
            text_snapshot_id=snapshot.raw_snapshot_id,
            extraction_method="html",
            links=[
                LinkHint(snippet=OFFICIAL_URL_SNIPPET, subject_id=project_id)
                for project_id in site.project_ids
            ],
        )
    )
    return result


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


DOCUMENT_DECLARATION = TypeDeclaration(
    creates=True,
    writes=frozenset({"title", "url", "publisher", "doc_type", "language", "license"}),
    match_rules=("document",),
)


class ProjectSitesCollector:
    """C2 ``project_sites`` (see the module docstring). Modes make no difference;
    ``limit`` caps the number of URLs."""

    NAME = COLLECTOR_NAME
    VERSION = 1
    DECLARATION: Mapping[str, TypeDeclaration] = {"document": DOCUMENT_DECLARATION}
    MODES: tuple[str, ...] = ()
    PARAMS: frozenset[str] = frozenset({"limit"})

    def run(self, ctx: RunContext) -> None:
        """Fetch and reconcile every input URL in canonical-URL order."""
        ctx.client.set_listing_host(None)  # every URL is its own unit
        patterns = soft_404_patterns(ctx.options)
        config = ctx.client.config
        sites = official_sites(ctx.live_records("project", ["official_urls"]), config.exclude_hosts)
        complete = True
        for site in sites[: ctx.params.get("limit")]:
            if ctx.cancelled():
                return
            if len(site.key) > MAX_KEY_CHARS:
                ctx.message(
                    "warning",
                    "invalid_value",
                    f"{site.url}: the URL is too long for an observation key; not requested",
                    url=site.url,
                )
                continue
            answered = _collect_site(ctx, site, patterns, config.licence.code)
            complete = complete and answered
        if complete:
            ctx.listing_complete()


def _collect_site(
    ctx: RunContext, site: SiteUrl, patterns: Mapping[str, Sequence[str]], default_licence: str
) -> bool:
    """Fetch one input URL and reconcile its document, or sight its key when the response
    gives none; True if the URL got a final response (any status)."""
    fetched = ctx.client.get(site.url)
    candidates: list[Candidate] = []
    snapshot = fetched.snapshot
    if fetched.ok and snapshot is None:
        ctx.message(
            "warning",
            "unsupported_content",
            f"{site.url}: the response has no body; no document",
            url=site.url,
        )
    elif fetched.ok and snapshot is not None:
        result = parse_site_page(
            snapshot, site, soft_404_patterns=patterns, default_licence=default_licence
        )
        ctx.count("pages_parsed")
        for code, text in result.warnings:
            ctx.message(
                "warning", code, text, url=snapshot.url, snapshot_id=snapshot.raw_snapshot_id
            )
        candidates = result.candidates
    for candidate in candidates:
        ctx.reconcile(candidate)
    if not candidates:
        ctx.observe("document", site.key, url=fetched.final_url or site.url)
    return fetched.status is not None


COLLECTOR = ProjectSitesCollector()
