"""The request guard (docs/API.md §1.1): one pure-ASGI middleware that checks every
request from its request line and headers, before routing and before any body byte is
read.

1. **Host allowlist** (every request; against DNS rebinding): the ``Host`` name without
   port must equal an ``ALLOWED_HOSTS`` entry (case-insensitive, no wildcards, no IPv6
   literals). ``X-Forwarded-Host`` and ``Forwarded`` are never read.
2. **Same-origin fetch** (every ``/api`` request except ``GET /api/health``):
   ``X-Requested-With: mdt`` is required, and ``Sec-Fetch-Site``, if sent, must be
   ``same-origin`` or ``none``.
3. **Writes** (every method except GET, HEAD and OPTIONS): a valid percent-encoded
   ``X-Author``, ``Content-Type: application/json``, an ``Origin`` (if sent) that matches
   the ``Host``, and a body of at most ``MAX_BODY_BYTES``, checked from
   ``Content-Length`` and by counting the streamed bytes.

The query string is limited to ``MAX_QUERY_BYTES`` (414). Rejections are answered with
the error envelope; the decoded author name is passed on in the ASGI scope
(:data:`AUTHOR_SCOPE_KEY`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from mdt.api.errors import error_response
from mdt.domain.actor import parse_author_header
from mdt.domain.errors import (
    AuthorInvalidError,
    AuthorRequiredError,
    CrossOriginForbiddenError,
    DomainError,
    InvalidHostError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    UriTooLongError,
)

MAX_BODY_BYTES: Final = 1024 * 1024
MAX_QUERY_BYTES: Final = 8 * 1024
#: Scope key holding the validated author name of a write.
AUTHOR_SCOPE_KEY: Final = "mdt.author"
API_PREFIX: Final = "/api"
HEALTH_PATH: Final = "/api/health"
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
SAME_ORIGIN_FETCH_SITES: Final = frozenset({b"same-origin", b"none"})
REQUESTED_WITH: Final = b"mdt"
JSON_MEDIA_TYPE: Final = "application/json"
DEFAULT_PORTS: Final = {"http": 80, "https": 443}

_ALLOWED_HOST_RE = re.compile(r"[a-z0-9._-]+")
_HOST_HEADER_RE = re.compile(r"(?P<host>[A-Za-z0-9._-]+)(?::(?P<port>[0-9]{1,5}))?")
_ORIGIN_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<host>[A-Za-z0-9._-]+)(?::(?P<port>[0-9]{1,5}))?"
)
_DIGITS_RE = re.compile(rb"[0-9]+")
_GUARDED_HEADERS: Final = (
    b"host",
    b"x-requested-with",
    b"sec-fetch-site",
    b"x-author",
    b"content-type",
    b"origin",
    b"content-length",
)


@dataclass(frozen=True)
class HostAllowlist:
    """The parsed ``ALLOWED_HOSTS`` setting."""

    hosts: frozenset[str]
    allow_any: bool = False

    @classmethod
    def parse(cls, entries: Sequence[str]) -> HostAllowlist:
        """Validate the entries: host names only; ``*`` (no Host check) only as the sole
        entry. Raises ``ValueError`` with a message for the operator."""
        names = [entry.strip().lower() for entry in entries if entry.strip()]
        if not names:
            raise ValueError("ALLOWED_HOSTS is empty; list the host names the app is reached at")
        if "*" in names:
            if len(names) > 1:
                raise ValueError("'*' in ALLOWED_HOSTS is allowed only as the only entry")
            return cls(frozenset(), allow_any=True)
        for name in names:
            if not _ALLOWED_HOST_RE.fullmatch(name):
                raise ValueError(
                    f"ALLOWED_HOSTS entry {name!r} is not a host name "
                    "(ports, wildcards and IPv6 literals are not supported)"
                )
        return cls(frozenset(names))

    def allows(self, hostname: str) -> bool:
        """True if requests for ``hostname`` (without port) are accepted."""
        return self.allow_any or hostname.lower() in self.hosts


class RequestTooLarge(HTTPException):
    """Raised while the body is streamed once it exceeds the limit. An ``HTTPException``,
    so FastAPI's body parsing re-raises it and the handlers answer ``413``."""

    def __init__(self) -> None:
        super().__init__(status_code=413)


# --------------------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------------------


def is_api_path(path: str) -> bool:
    """True for ``/api`` and everything below it."""
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def _ascii(value: bytes) -> str | None:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return None


def _port(raw: str | None) -> int | None:
    """The port number (None without a port); ``ValueError`` if it is out of range."""
    if raw is None:
        return None
    number = int(raw)
    if not 0 < number <= 65535:
        raise ValueError("port out of range")
    return number


def parse_host(values: Sequence[bytes]) -> tuple[str, int | None] | None:
    """``(hostname, port)`` from the ``Host`` header (hostname lower-cased), or None if
    the header is missing, repeated or malformed (IPv6 literals are unsupported)."""
    if len(values) != 1:
        return None
    text = _ascii(values[0])
    match = _HOST_HEADER_RE.fullmatch(text) if text is not None else None
    if match is None:
        return None
    try:
        return match["host"].lower(), _port(match["port"])
    except ValueError:
        return None


def normalize_authority(host: str, port: int | None, scheme: str) -> str:
    """Lower-cased host without trailing dot, plus ``:port`` unless it is the default
    port of ``scheme`` (API §1.1)."""
    name = host.lower().removesuffix(".")
    if port is None or port == DEFAULT_PORTS[scheme]:
        return name
    return f"{name}:{port}"


def parse_origin(value: str) -> tuple[str, str] | None:
    """``(scheme, normalised authority)`` of an ``Origin`` value, or None for ``null``,
    other schemes and anything that is not ``scheme://host[:port]``."""
    match = _ORIGIN_RE.fullmatch(value)
    if match is None:
        return None
    scheme = match["scheme"].lower()
    if scheme not in DEFAULT_PORTS or not match["host"].removesuffix("."):
        return None
    try:
        port = _port(match["port"])
    except ValueError:
        return None
    return scheme, normalize_authority(match["host"], port, scheme)


def _header_values(scope: Scope) -> dict[bytes, list[bytes]]:
    values: dict[bytes, list[bytes]] = {name: [] for name in _GUARDED_HEADERS}
    for name, value in scope.get("headers", ()):
        key = bytes(name).lower()
        if key in values:
            values[key].append(bytes(value))
    return values


# --------------------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------------------


def _check_host(values: Sequence[bytes], allowed_hosts: HostAllowlist) -> None:
    if allowed_hosts.allow_any:
        return
    host = parse_host(values)
    if host is None or not allowed_hosts.allows(host[0]):
        raise InvalidHostError()


def _check_same_origin_fetch(headers: dict[bytes, list[bytes]]) -> None:
    if headers[b"x-requested-with"] != [REQUESTED_WITH]:
        raise CrossOriginForbiddenError("The header X-Requested-With: mdt is required")
    sites = headers[b"sec-fetch-site"]
    if sites and (len(sites) != 1 or sites[0] not in SAME_ORIGIN_FETCH_SITES):
        raise CrossOriginForbiddenError("Cross-site requests are refused")


def _check_author(values: Sequence[bytes]) -> str:
    if not values:
        raise AuthorRequiredError()
    if len(values) > 1:
        raise AuthorInvalidError("The X-Author header must occur only once")
    encoded = _ascii(values[0])
    if encoded is None:
        raise AuthorInvalidError("The X-Author header must be percent-encoded UTF-8")
    return parse_author_header([encoded])


def _check_content_type(values: Sequence[bytes]) -> None:
    text = _ascii(values[0]) if len(values) == 1 else None
    if text is None or text.split(";", 1)[0].strip().lower() != JSON_MEDIA_TYPE:
        raise UnsupportedMediaTypeError()


def _check_origin(origin_values: Sequence[bytes], host_values: Sequence[bytes]) -> None:
    if not origin_values:
        return
    text = _ascii(origin_values[0]) if len(origin_values) == 1 else None
    origin = parse_origin(text) if text is not None else None
    if origin is None:
        raise CrossOriginForbiddenError("The Origin header is not a valid origin")
    scheme, authority = origin
    host = parse_host(host_values)
    if host is None or normalize_authority(host[0], host[1], scheme) != authority:
        raise CrossOriginForbiddenError("The Origin does not match the Host")


def _check_content_length(values: Sequence[bytes], max_body_bytes: int) -> None:
    for value in values:
        text = value.strip()
        if _DIGITS_RE.fullmatch(text) and int(text) > max_body_bytes:
            raise PayloadTooLargeError(
                f"The request body must be at most {max_body_bytes // 1024} KiB"
            )


def inspect_request(
    scope: Scope,
    allowed_hosts: HostAllowlist,
    *,
    max_body_bytes: int = MAX_BODY_BYTES,
    max_query_bytes: int = MAX_QUERY_BYTES,
) -> str | None:
    """Run every check on an HTTP scope; raise the :class:`DomainError` of the first
    failing one. Returns the validated author name for writes, else None."""
    headers = _header_values(scope)
    _check_host(headers[b"host"], allowed_hosts)
    if len(scope.get("query_string", b"")) > max_query_bytes:
        raise UriTooLongError(f"The query string must be at most {max_query_bytes // 1024} KiB")
    method, path = scope["method"], scope["path"]
    if is_api_path(path) and not (method == "GET" and path == HEALTH_PATH):
        _check_same_origin_fetch(headers)
    if method in SAFE_METHODS:
        return None
    author = _check_author(headers[b"x-author"])
    _check_content_type(headers[b"content-type"])
    _check_origin(headers[b"origin"], headers[b"host"])
    _check_content_length(headers[b"content-length"], max_body_bytes)
    return author


def _limited_receive(receive: Receive, limit: int) -> Receive:
    """``receive`` that raises :class:`RequestTooLarge` once the body exceeds ``limit``."""
    received = 0

    async def receive_limited() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                raise RequestTooLarge()
        return message

    return receive_limited


class RequestGuardMiddleware:
    """The guard as ASGI middleware; it answers rejections itself and never reads the
    body of a rejected request. WebSocket connections are refused (there are none)."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: HostAllowlist,
        *,
        max_body_bytes: int = MAX_BODY_BYTES,
        max_query_bytes: int = MAX_QUERY_BYTES,
    ) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.max_body_bytes = max_body_bytes
        self.max_query_bytes = max_query_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            author = inspect_request(
                scope,
                self.allowed_hosts,
                max_body_bytes=self.max_body_bytes,
                max_query_bytes=self.max_query_bytes,
            )
        except DomainError as error:
            await error_response(error)(scope, receive, send)
            return
        if author is not None:
            scope[AUTHOR_SCOPE_KEY] = author
            receive = _limited_receive(receive, self.max_body_bytes)
        await self.app(scope, receive, send)
