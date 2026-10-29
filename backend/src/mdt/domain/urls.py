"""URL normalisation (docs/DATA_MODEL.md §1.2) and canonical URLs (§3.4)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_URL_LENGTH = 2000

_HOST_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*\.?$")
_IPV6_RE = re.compile(r"^\[[0-9A-Fa-f:.]+\]$")
_PORT_RE = re.compile(r"^[0-9]{1,5}$")
_DEFAULT_PORTS = {"http": "80", "https": "443"}


class UrlError(ValueError):
    """The value is not an acceptable URL."""


@dataclass(frozen=True)
class _Parts:
    scheme: str
    host: str
    port: str | None
    rest: str  # path, query and fragment exactly as given


def _is_forbidden_char(char: str) -> bool:
    if char.isspace():
        return True
    code_point = ord(char)
    # C0 controls, DEL and C1 controls; unpaired surrogates (category Cs) are not text.
    return (
        code_point < 0x20
        or 0x7F <= code_point <= 0x9F
        or 0xD800 <= code_point <= 0xDFFF
        or unicodedata.category(char) == "Cc"
    )


def _split(value: str) -> _Parts:
    scheme, sep, remainder = value.partition(":")
    if not sep or scheme.lower() not in _DEFAULT_PORTS:
        raise UrlError("the scheme must be http or https")
    if not remainder.startswith("//"):
        raise UrlError("the URL must contain a host")
    after = remainder[2:]
    end = len(after)
    for delimiter in "/?#":
        index = after.find(delimiter)
        if index != -1:
            end = min(end, index)
    netloc, rest = after[:end], after[end:]
    if "@" in netloc:
        raise UrlError("user information in URLs is not allowed")
    if netloc.startswith("["):
        close = netloc.find("]")
        if close == -1:
            raise UrlError("invalid IPv6 host")
        host, port_part = netloc[: close + 1], netloc[close + 1 :]
        if port_part and not port_part.startswith(":"):
            raise UrlError("invalid host")
        port = port_part[1:] if port_part else None
    elif ":" in netloc:
        host, port = netloc.rsplit(":", 1)
    else:
        host, port = netloc, None
    if not host:
        raise UrlError("the URL must contain a host")
    if port is not None and (not _PORT_RE.fullmatch(port) or not 0 < int(port) <= 65535):
        raise UrlError("invalid port")
    return _Parts(scheme.lower(), host, port, rest)


def _encode_host(host: str) -> str:
    if host.startswith("["):
        if not _IPV6_RE.fullmatch(host):
            raise UrlError("invalid IPv6 host")
        return host.lower()
    try:
        encoded = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UrlError("invalid host name") from exc
    if not _HOST_RE.fullmatch(encoded):
        raise UrlError("invalid host name")
    return encoded


def normalize_url(value: str) -> str:
    """Normalise a URL: trimmed; http/https only (scheme lower-cased); non-empty host,
    IDNA-encoded; no user information; no whitespace or control characters; at most
    2 000 characters. Raises :class:`UrlError`."""
    value = value.strip()
    if not value:
        raise UrlError("the URL is empty")
    if any(_is_forbidden_char(char) for char in value):
        raise UrlError(
            "URLs must not contain whitespace, control characters or unpaired surrogates"
        )
    parts = _split(value)
    host = _encode_host(parts.host)
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    result = f"{parts.scheme}://{netloc}{parts.rest}"
    if len(result) > MAX_URL_LENGTH:
        raise UrlError(f"URLs must not be longer than {MAX_URL_LENGTH} characters")
    return result


def canonical_url(url: str) -> str:
    """Canonical form of a normalised URL used for duplicate detection.

    Lower-case scheme and host; no trailing dot on the host; no default port; no
    fragment; no ``utm_*`` query parameters; no trailing slash except for the root path.
    """
    parts = _split(normalize_url(url))
    host = parts.host.lower().rstrip(".")
    port = None if parts.port == _DEFAULT_PORTS[parts.scheme] else parts.port
    rest = parts.rest.split("#", 1)[0]
    path, _, query = rest.partition("?")
    kept = [
        segment
        for segment in query.split("&")
        if segment and not segment.split("=", 1)[0].lower().startswith("utm_")
    ]
    path = path.rstrip("/") or "/"
    netloc = host if port is None else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}{path}" + (f"?{'&'.join(kept)}" if kept else "")
