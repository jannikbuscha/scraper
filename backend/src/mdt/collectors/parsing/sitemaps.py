"""Sitemaps (``urlset`` and ``sitemapindex``) parsed with ElementTree (docs/COLLECTORS.md
§7.1, §13; C3, C4b).

A sitemap's ``lastmod`` is never a publication date (§7.1): collectors use it to select a
window (C4b) or keep it in an observation's details (C3). ``www.kmu.gov.ua/sitemap.xml``
lists its child sitemaps as a ``urlset``, so callers decide by the URLs, not by the root
element alone.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Literal

from mdt.collectors.parsing import ParseError

SitemapKind = Literal["urlset", "sitemapindex"]
_ITEM_TAGS = {"urlset": "url", "sitemapindex": "sitemap"}
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class SitemapEntry:
    """One ``<url>`` or ``<sitemap>`` entry: ``loc`` and ``lastmod`` as written."""

    loc: str
    lastmod: str | None = None

    @property
    def lastmod_date(self) -> str | None:
        """The calendar date written in ``lastmod`` (its first ten characters), or None."""
        if not self.lastmod:
            return None
        match = _DATE_PREFIX.match(self.lastmod.strip())
        if match is None:
            return None
        try:
            return date.fromisoformat(match.group(1)).isoformat()
        except ValueError:
            return None


@dataclass(frozen=True)
class Sitemap:
    """A parsed sitemap: its root kind and entries in document order."""

    kind: SitemapKind
    entries: tuple[SitemapEntry, ...]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(body: bytes) -> Sitemap:
    """Parse a sitemap body. Raises ParseError for a body that is not XML, a root other
    than ``urlset`` or ``sitemapindex``, or an entry without ``loc``."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ParseError("the sitemap is not well-formed XML") from exc
    kind = _local(root.tag)
    if kind not in _ITEM_TAGS:
        raise ParseError("the sitemap root is neither urlset nor sitemapindex")
    entries: list[SitemapEntry] = []
    for item in root:
        if _local(item.tag) != _ITEM_TAGS[kind]:
            continue
        values = {_local(child.tag): (child.text or "").strip() for child in item}
        loc = values.get("loc")
        if not loc:
            raise ParseError(f"a sitemap {_ITEM_TAGS[kind]} entry has no loc")
        entries.append(SitemapEntry(loc=loc, lastmod=values.get("lastmod") or None))
    return Sitemap(kind="urlset" if kind == "urlset" else "sitemapindex", entries=tuple(entries))
