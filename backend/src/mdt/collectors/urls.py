"""URLs and hosts as the polite client requests them (docs/COLLECTORS.md §4.1).

Only ``http`` and ``https`` URLs without user information. The host is lower-cased,
IDNA-encoded and stripped of a trailing dot (``diia.gov.ua.`` → ``diia.gov.ua``) and of a
default port; an empty path becomes ``/``; path and query keep their case; the fragment is
removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from mdt.domain.urls import UrlError, normalize_url

_DEFAULT_PORTS = {"http": 80, "https": 443}

__all__ = ["FetchUrl", "UrlError", "normalize_host", "parse_fetch_url", "resolve_location"]


@dataclass(frozen=True)
class FetchUrl:
    """A normalised URL and its parts."""

    url: str
    scheme: str
    host: str
    port: int | None  # an explicit non-default port
    target: str  # path and query, e.g. "/projects?page=2"

    @property
    def origin(self) -> str:
        """``scheme://host[:port]``: the unit robots.txt applies to (RFC 9309)."""
        netloc = self.host if self.port is None else f"{self.host}:{self.port}"
        return f"{self.scheme}://{netloc}"

    @property
    def robots_url(self) -> str:
        """The robots.txt URL of the origin."""
        return f"{self.origin}/robots.txt"

    @property
    def path(self) -> str:
        """The path without the query."""
        return self.target.split("?", 1)[0]


def normalize_host(host: str) -> str:
    """A host name as the client compares it: IDNA, lower-case, no trailing dot."""
    return parse_fetch_url(f"https://{host.strip()}/").host


def parse_fetch_url(url: str) -> FetchUrl:
    """Normalise ``url`` (raises :class:`UrlError` for anything the client must not request)."""
    normalised = normalize_url(url)
    scheme, _, remainder = normalised.partition("://")
    end = len(remainder)
    for delimiter in "/?#":
        index = remainder.find(delimiter)
        if index != -1:
            end = min(end, index)
    netloc, rest = remainder[:end], remainder[end:]
    rest = rest.split("#", 1)[0]
    if netloc.startswith("["):
        host, _, port_text = netloc[1:].partition("]")
        host = f"[{host.lower()}]"
        port_text = port_text.removeprefix(":")
    else:
        host, _, port_text = netloc.partition(":")
        host = host.lower().rstrip(".")
    if not host or host == "[]":
        raise UrlError("the URL must contain a host")
    port = int(port_text) if port_text else None
    if port == _DEFAULT_PORTS[scheme]:
        port = None
    if not rest.startswith("/"):
        rest = "/" + rest
    netloc = host if port is None else f"{host}:{port}"
    return FetchUrl(f"{scheme}://{netloc}{rest}", scheme, host, port, rest)


def resolve_location(base: str, location: str) -> str:
    """The absolute URL of a redirect ``Location`` (relative values resolve against
    ``base``)."""
    return urljoin(base, location.strip())
