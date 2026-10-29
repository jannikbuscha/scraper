"""Security headers on every response (docs/API.md §6).

One pure-ASGI middleware adds the headers to every HTTP response: API responses, static
files, the SPA fallback and every error, including the guard's rejections and Starlette's
500 responses (it wraps the whole application).
"""

from __future__ import annotations

from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
SECURITY_HEADERS: Final[tuple[tuple[str, str], ...]] = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)


class SecurityHeadersMiddleware:
    """Set :data:`SECURITY_HEADERS` on every HTTP response (replacing any earlier value)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=list(message.get("headers", [])))
                for name, value in SECURITY_HEADERS:
                    headers[name] = value
                message = {**message, "headers": headers.raw}
            await send(message)

        await self.app(scope, receive, send_with_headers)
