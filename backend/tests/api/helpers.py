"""Helpers of the HTTP API tests: a client wrapper that writes like the UI, direct ASGI
calls (to see whether a request body was read) and synthetic records."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.types import Message

BASE_URL = "http://127.0.0.1:8080"
HOST = "127.0.0.1:8080"
ALICE = "Alice Example"
BOB = "Bob Example"

_counter = itertools.count(1)


def encode_author(name: str) -> str:
    """The header value the UI sends: ``encodeURIComponent(name)``."""
    return quote(name, safe="!~*'()")


def unique_slug(prefix: str = "example") -> str:
    """A slug that no other test record uses."""
    return f"{prefix}-{next(_counter)}"


def project_data(**overrides: Any) -> dict[str, Any]:
    """A valid synthetic project (a project needs a scope note on create)."""
    return {
        "slug": unique_slug(),
        "name_en": "Example project",
        "scope_note": "Synthetic scope note.",
        **overrides,
    }


def error_of(response: Response) -> dict[str, Any]:
    """The error object of an error response (asserts the envelope shape)."""
    body = response.json()
    assert set(body) == {"error"}, body
    error = body["error"]
    assert set(error) == {"code", "message", "details"}, error
    assert isinstance(error["message"], str) and error["message"]
    return dict(error)


class ApiClient:
    """A TestClient wrapper: reads send ``X-Requested-With``; writes also send
    ``X-Author`` and a JSON body, like the UI's fetch wrapper."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Response:
        """GET ``path`` with query parameters."""
        return self.client.get(path, params=dict(params) if params else None)

    def write(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        author: str = ALICE,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Send a write with the author header and a JSON body (``{}`` if None)."""
        return self.client.request(
            method,
            path,
            json={} if body is None else body,
            headers={"X-Author": encode_author(author), **(headers or {})},
        )

    def post(self, path: str, body: Any = None, *, author: str = ALICE) -> Response:
        """POST JSON as ``author``."""
        return self.write("POST", path, body, author=author)

    def patch(self, path: str, body: Any = None, *, author: str = ALICE) -> Response:
        """PATCH JSON as ``author``."""
        return self.write("PATCH", path, body, author=author)

    # Shortcuts ------------------------------------------------------------------------

    def ok(self, response: Response, status: int = 200) -> dict[str, Any]:
        """The JSON body of a successful response."""
        assert response.status_code == status, (response.status_code, response.text)
        return dict(response.json())

    def create(
        self, entity_type: str, data: Mapping[str, Any], *, author: str = ALICE
    ) -> dict[str, Any]:
        """Create an entity; returns the item."""
        response = self.post(f"/api/entities/{entity_type}", {"data": dict(data)}, author=author)
        return dict(self.ok(response, 201)["item"])

    def create_project(self, **overrides: Any) -> dict[str, Any]:
        """Create a synthetic project; returns the item."""
        return self.create("project", project_data(**overrides))

    def item(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        """The detail item."""
        return dict(self.ok(self.get(f"/api/entities/{entity_type}/{entity_id}"))["item"])

    def update(
        self,
        entity_type: str,
        item: Mapping[str, Any],
        changes: Mapping[str, Any],
        *,
        note: str | None = None,
        author: str = ALICE,
    ) -> dict[str, Any]:
        """PATCH ``changes`` with the item's version; returns the response body."""
        body = {"expected_version": item["version"], "changes": dict(changes), "note": note}
        response = self.patch(f"/api/entities/{entity_type}/{item['id']}", body, author=author)
        return self.ok(response)

    def comment(
        self,
        subject_id: str,
        body_md: str = "Example comment.",
        *,
        field: str | None = None,
        parent_id: str | None = None,
        author: str = ALICE,
    ) -> dict[str, Any]:
        """Create a comment; returns it."""
        body = {
            "subject_id": subject_id,
            "field": field,
            "parent_id": parent_id,
            "body_md": body_md,
        }
        return dict(self.ok(self.post("/api/comments", body, author=author), 201)["comment"])

    def list(self, entity_type: str, **params: Any) -> dict[str, Any]:
        """One page of a list."""
        return self.ok(self.get(f"/api/entities/{entity_type}", params))


# --------------------------------------------------------------------------------------
# Direct ASGI calls
# --------------------------------------------------------------------------------------


@dataclass
class AsgiResult:
    """The response of a direct ASGI call and whether the app read the request body."""

    status: int
    headers: dict[str, str]
    body: bytes
    body_read: bool


def call_asgi(
    app: FastAPI,
    method: str,
    path: str,
    headers: Sequence[tuple[str, str | bytes]] = (),
    *,
    body: bytes = b"",
    query_string: bytes = b"",
    host: str | None = HOST,
) -> AsgiResult:
    """Call the ASGI app with a hand-made scope. ``path`` is the decoded path, as an ASGI
    server passes it (``/%2e%2e/x`` arrives as ``/../x``)."""
    raw_headers = [] if host is None else [(b"host", host.encode("latin-1"))]
    for name, value in headers:
        raw = value if isinstance(value, bytes) else value.encode("latin-1")
        raw_headers.append((name.lower().encode("latin-1"), raw))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8080),
        "state": {},
    }
    read = False
    messages: list[Message] = []

    async def receive() -> Message:
        nonlocal read
        read = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    async def call() -> None:
        await app(scope, receive, send)

    anyio.run(call)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    response_headers = {
        name.decode("latin-1"): value.decode("latin-1") for name, value in start["headers"]
    }
    return AsgiResult(start["status"], response_headers, content, read)
