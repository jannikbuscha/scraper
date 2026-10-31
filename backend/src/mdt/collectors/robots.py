"""robots.txt interpretation (docs/COLLECTORS.md §4.2): RFC 9309 through protego (longest
match, ``*`` and ``$``, Allow wins ties), after a preprocessing that makes the files seen in
Phase 0b behave as their owners meant (docs/SOURCES.md §2).

This module is pure: :mod:`mdt.collectors.client` fetches robots.txt and turns the response
into a :class:`RobotsPolicy` with :func:`policy_from_response`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from protego import Protego

#: Our product token: the robots.txt group we follow, else ``*``.
PRODUCT_TOKEN = "MDT-Portfolio-Research"

PolicyState = Literal["rules", "allow_all", "blocked", "unavailable"]

#: The fields that make a body a robots.txt (others, e.g. ``Host``, do not count).
_ROBOTS_FIELDS = frozenset({"user-agent", "allow", "disallow", "crawl-delay", "sitemap"})
_FIELD_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:")
_HTML_MARKERS = ("<html", "<!doctype html", "<head", "<body")


@dataclass(frozen=True)
class RobotsPolicy:
    """The robots.txt decision for one origin in one run."""

    state: PolicyState
    reason: str
    parser: Protego | None = None
    status: int | None = None
    snapshot_id: str | None = None

    def allows(self, url: str) -> bool:
        """May ``url`` (of this origin) be requested?"""
        if self.state == "allow_all":
            return True
        if self.state == "rules" and self.parser is not None:
            return bool(self.parser.can_fetch(url, PRODUCT_TOKEN))
        return False

    def crawl_delay(self) -> float | None:
        """``Crawl-delay`` of our group, in seconds."""
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(PRODUCT_TOKEN)
        return None if delay is None else float(delay)

    def request_interval(self) -> float | None:
        """Seconds per request from ``Request-rate`` of our group (``1/5s`` → 5)."""
        if self.parser is None:
            return None
        rate = self.parser.request_rate(PRODUCT_TOKEN)
        if rate is None or not rate.requests:
            return None
        return float(rate.seconds) / float(rate.requests)

    def describe(self) -> str:
        """A short decision text for ``mdt sources check``."""
        return self.reason


def _field_of(line: str) -> str | None:
    match = _FIELD_LINE.match(line.split("#", 1)[0])
    return match.group(1).lower() if match else None


def preprocess(body: bytes) -> str | None:
    """The text to parse, or None when the body is no robots.txt at all (allow all).

    A UTF-8 BOM is removed. A body that starts with ``<`` (after whitespace), or an HTML
    body without any robots field, is no robots.txt (plan2.diia.gov.ua). Lines that are not
    ``field: value`` (e.g. HTML after the rules, usf.com.ua) are dropped, so the parser's
    lenient ``field value`` reading never applies to them. Allow/Disallow lines without any
    ``User-agent`` line get ``User-agent: *`` prepended, so they are honoured
    (playcity.gov.ua).
    """
    text = body.decode("utf-8", errors="replace").removeprefix("﻿")
    if text.lstrip().startswith("<"):
        return None
    kept: list[str] = []
    fields: set[str] = set()
    for line in text.splitlines():
        content = line.split("#", 1)[0].strip()
        if not content:
            kept.append(line)
            continue
        field_name = _field_of(line)
        if field_name is None:
            continue
        fields.add(field_name)
        kept.append(line)
    lowered = text.lower()
    if not fields & _ROBOTS_FIELDS and any(marker in lowered for marker in _HTML_MARKERS):
        return None
    if fields & {"allow", "disallow"} and "user-agent" not in fields:
        kept.insert(0, "User-agent: *")
    return "\n".join(kept) + "\n"


def parse(body: bytes) -> Protego | None:
    """The parsed rules of a 2xx robots.txt body, or None for "allow all"."""
    text = preprocess(body)
    return None if text is None else Protego.parse(text)


def policy_from_response(
    status: int | None,
    body: bytes | None,
    *,
    challenge: bool = False,
    snapshot_id: str | None = None,
) -> RobotsPolicy:
    """The policy for a robots.txt response (``status`` None: no response at all).

    401, 403, 429 or a challenge page block the host; 404 and 410 allow all; any other
    status (other 4xx, 5xx after the retries) or no response makes robots.txt unavailable.
    """
    if challenge:
        return RobotsPolicy("blocked", "challenge page on robots.txt", None, status, snapshot_id)
    if status is None:
        return RobotsPolicy("unavailable", "no response", None, None, snapshot_id)
    if status in (401, 403, 429):
        return RobotsPolicy("blocked", f"HTTP {status} on robots.txt", None, status, snapshot_id)
    if status in (404, 410):
        return RobotsPolicy("allow_all", f"HTTP {status}: allow all", None, status, snapshot_id)
    if 200 <= status < 300:
        parser = parse(body or b"")
        if parser is None:
            return RobotsPolicy("allow_all", "no robots.txt: allow all", None, status, snapshot_id)
        return RobotsPolicy("rules", "rules", parser, status, snapshot_id)
    return RobotsPolicy("unavailable", f"HTTP {status}", None, status, snapshot_id)
