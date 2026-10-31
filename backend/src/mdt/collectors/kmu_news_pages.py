# ruff: noqa: RUF002
"""Parsers of C4b ``kmu_news`` (docs/COLLECTORS.md §8.4, SOURCES S4b): the sitemaps of
www.kmu.gov.ua and its news pages, and the relevance rule. Pure functions of a snapshot (no
network, no database, no clock), except :func:`relevance`, which takes the run's alias index.

* ``/sitemap.xml`` is a ``urlset`` whose locations are child sitemaps; the post sitemaps
  (``sitemap-rainlab-blog-models-post-<n>.xml``, English ones under ``/en/``) list the news
  pages ``/news/<slug>`` and ``/en/news/<slug>`` with ``lastmod``.
* A news page (``news_page``): ``h1`` is the title; ``div.page_title-desc`` names the
  publishing body (Ukrainian pages: a link and its host; English: plain text) and the date
  (Kyiv local time, ``опубліковано DD <month> YYYY року о HH:MM`` / ``posted D Month YYYY
  HH:MM``); ``ul.wcag-tags`` holds the topics; ``div.editor-content`` is the text; the footer
  gives the licence. Scripts, nonces, csrf tokens and the bot-manager token are never read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from bs4.element import Tag

from mdt.collectors.base import Candidate, Evidence, Snapshot
from mdt.collectors.parsing import ParseError, ParseResult
from mdt.collectors.parsing.dates import find_posted_datetime
from mdt.collectors.parsing.html_text import html_text, read_page
from mdt.collectors.parsing.language import kmu_language
from mdt.collectors.parsing.sitemaps import parse_sitemap
from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.collectors.tagger import AliasIndex
from mdt.collectors.urls import UrlError, parse_fetch_url

HOST = "www.kmu.gov.ua"
PUBLISHER = HOST
EXTRACTION_METHOD = "selector"
STATED = "stated_in_source"
#: The host a Ukrainian page's publishing-body link points to when the ministry published it.
MINISTRY_HOST = "thedigital.gov.ua"
#: The publishing body of an English page published by the ministry (case-folded match).
MINISTRY_EN = "ministry of digital transformation"
NOT_FOUND_STATUSES = frozenset({404, 410})
_POST_SITEMAP = re.compile(r"/(?P<en>en/)?sitemap-rainlab-blog-models-post-\d+\.xml")
_NEWS_PATH = re.compile(r"/(?P<en>en/)?news/(?P<slug>[^/]+)")
_DATE_WORDS = re.compile(r"\b(?:опубліковано|posted)\b", re.IGNORECASE)


# --------------------------------------------------------------------------------------
# Sitemaps
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """A news entry of a post sitemap: language, slug, URL and ``lastmod`` as written."""

    language: str  # uk | en
    slug: str
    url: str
    lastmod: str | None = None
    day: str | None = None  # the calendar date written in lastmod (window selection only)

    @property
    def key(self) -> str:
        """The observation key and ``external_id``: ``uk:<slug>`` or ``en:<slug>``."""
        return f"{self.language}:{self.slug}"


def _on_site(loc: str) -> tuple[str, str] | None:
    """The normalised URL and path of a sitemap location on www.kmu.gov.ua, else None."""
    try:
        target = parse_fetch_url(loc)
    except UrlError:
        return None
    return (target.url, target.path) if target.host == HOST else None


def parse_sitemap_index(snapshot: Snapshot) -> tuple[list[str], list[str]]:
    """The post sitemaps that ``/sitemap.xml`` lists, Ukrainian and English, in listed
    order (the file is a ``urlset`` whose locations are child sitemaps). Raises
    :class:`ParseError` when it lists no Ukrainian post sitemap."""
    ukrainian: list[str] = []
    english: list[str] = []
    for entry in parse_sitemap(snapshot.body).entries:
        found = _on_site(entry.loc)
        match = _POST_SITEMAP.fullmatch(found[1]) if found else None
        if found is None or match is None:
            continue
        target = english if match["en"] else ukrainian
        if found[0] not in target:
            target.append(found[0])
    if not ukrainian:
        raise ParseError("sitemap.xml lists no Ukrainian post sitemap")
    return ukrainian, english


def parse_post_sitemap(snapshot: Snapshot, language: str) -> list[Entry]:
    """The news entries of a post sitemap of ``language`` in document order; other
    locations are skipped. Raises :class:`ParseError` for anything but a ``urlset``."""
    sitemap = parse_sitemap(snapshot.body)
    if sitemap.kind != "urlset":
        raise ParseError("a post sitemap must be a urlset")
    entries: list[Entry] = []
    for item in sitemap.entries:
        found = _on_site(item.loc)
        match = _NEWS_PATH.fullmatch(found[1]) if found else None
        if found is None or match is None or bool(match["en"]) != (language == "en"):
            continue
        entries.append(Entry(language, match["slug"], found[0], item.lastmod, item.lastmod_date))
    return entries


# --------------------------------------------------------------------------------------
# News pages
# --------------------------------------------------------------------------------------


def key_of(url: str) -> str:
    """The key of a news URL (``/news/<slug>`` → ``uk:<slug>``, ``/en/news/<slug>`` →
    ``en:<slug>``). Raises :class:`ParseError` for other URLs."""
    found = _on_site(url)
    match = _NEWS_PATH.fullmatch(found[1]) if found else None
    if match is None:
        raise ParseError(f"{url} is no news page of {HOST}")
    return f"{'en' if match['en'] else 'uk'}:{match['slug']}"


def _publishing_body(header: Tag, language: str) -> tuple[str | None, list[str], bool]:
    """The publishing body as stated before the date words, the hosts its links point to,
    and whether it is the ministry."""
    text = collapse_whitespace(header.get_text(" "))
    body = _DATE_WORDS.split(text, maxsplit=1)[0].strip(" ,") or None
    hosts: list[str] = []
    for link in header.find_all("a", href=True):
        host = (urlsplit(str(link["href"]).strip()).hostname or "").removeprefix("www.")
        if host and host not in hosts:
            hosts.append(host)
    ministry = MINISTRY_HOST in hosts or (
        language == "en" and body is not None and MINISTRY_EN in body.casefold()
    )
    return body, hosts, ministry


def parse_news_page(
    snapshot: Snapshot, *, focal_org_id: str | None, default_licence: str | None
) -> ParseResult:
    """A news page (``news_page``): the document candidate with its publishing body,
    date, topics, text and licence. ``h1`` is the title; ``div.page_title-desc`` names the
    publishing body and the date (Kyiv local time); ``ul.wcag-tags`` holds the topics
    (observation details); ``div.editor-content`` is the text. The candidate's
    ``details.ministry`` says whether the ministry published it (then ``publisher_org_id``
    is the focal organisation). A 404 or 410 is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    key = key_of(snapshot.url or "")
    url = snapshot.final_url or snapshot.url or ""
    page = read_page(snapshot)
    heading = page.soup.find("h1")
    title = collapse_whitespace(heading.get_text(" ")) if isinstance(heading, Tag) else ""
    if not title:
        raise ParseError(f"{url}: no h1")
    content = page.soup.select_one("div.editor-content")
    if content is None:
        raise ParseError(f"{url}: no div.editor-content")
    result = ParseResult(warnings=list(page.warnings))
    language = kmu_language(url)
    fields: dict[str, Any] = {
        "doc_type": "news",
        "title": title,
        "url": url,
        "publisher": PUBLISHER,
        "language": language,
        "license": page.licence or default_licence,
    }
    header = page.soup.select_one("div.page_title-desc")
    body: str | None = None
    hosts: list[str] = []
    ministry = False
    if header is None:
        result.warn("invalid_value", f"{url}: no div.page_title-desc (publishing body, date)")
    else:
        body, hosts, ministry = _publishing_body(header, language)
        posted = find_posted_datetime(header.get_text(" "))
        if posted is None:
            result.warn("invalid_value", f"{url}: no publication date in the page header")
        else:
            result.warnings.extend((code, f"{url}: {text}") for code, text in posted.warnings)
            fields |= {"published": posted.date, "published_basis": STATED}
            fields |= {"published_text": posted.text, "published_at_utc": posted.utc}
    if ministry and focal_org_id is not None:
        fields["publisher_org_id"] = focal_org_id
    tags = page.soup.select_one("ul.wcag-tags")
    topics = [] if tags is None else [collapse_whitespace(li.get_text(" ")) for li in tags("li")]
    text = html_text(content)
    result.candidates.append(
        Candidate(
            entity_type="document",
            key=key,
            evidence=Evidence(raw_snapshot_id=snapshot.raw_snapshot_id, source_url=url),
            label=title,
            url=url,
            external_id=key,
            fields={name: value for name, value in fields.items() if value is not None},
            text=text or None,
            text_snapshot_id=snapshot.raw_snapshot_id,
            extraction_method=EXTRACTION_METHOD,
            details={
                "publishing_body": body,
                "publishing_body_hosts": hosts,
                "ministry": ministry,
                "topics": [topic for topic in topics if topic],
            },
        )
    )
    return result


def relevance(candidate: Candidate, aliases: AliasIndex) -> str | None:
    """Why a Ukrainian page is kept (``publishing_body`` or ``alias_match``), else None."""
    if candidate.details.get("ministry"):
        return "publishing_body"
    if aliases.matches(candidate.label or "") or aliases.matches(candidate.text or ""):
        return "alias_match"
    return None
