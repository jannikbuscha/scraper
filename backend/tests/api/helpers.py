"""Helpers of the HTTP API tests: a client wrapper that writes like the UI, direct ASGI
calls (with a hand-made path) and synthetic records."""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.types import Message

BASE_URL = "http://127.0.0.1:8080"
HOST = "127.0.0.1:8080"
#: The name every write through the API is recorded under.
USER = "user"

_counter = itertools.count(1)


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
    """A TestClient wrapper: writes send a JSON body, like the UI's fetch wrapper."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Response:
        """GET ``path`` with query parameters."""
        return self.client.get(path, params=dict(params) if params else None)

    def write(self, method: str, path: str, body: Any = None) -> Response:
        """Send a write with a JSON body (``{}`` if None)."""
        return self.client.request(method, path, json={} if body is None else body)

    def post(self, path: str, body: Any = None) -> Response:
        """POST JSON."""
        return self.write("POST", path, body)

    def patch(self, path: str, body: Any = None) -> Response:
        """PATCH JSON."""
        return self.write("PATCH", path, body)

    # Shortcuts ------------------------------------------------------------------------

    def ok(self, response: Response, status: int = 200) -> dict[str, Any]:
        """The JSON body of a successful response."""
        assert response.status_code == status, (response.status_code, response.text)
        return dict(response.json())

    def create(self, entity_type: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """Create an entity; returns the item."""
        response = self.post(f"/api/entities/{entity_type}", {"data": dict(data)})
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
    ) -> dict[str, Any]:
        """PATCH ``changes``; returns the response body."""
        body = {"changes": dict(changes), "note": note}
        response = self.patch(f"/api/entities/{entity_type}/{item['id']}", body)
        return self.ok(response)

    def comment(
        self,
        subject_id: str,
        body_md: str = "Example comment.",
        *,
        field: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a comment; returns it."""
        body = {
            "subject_id": subject_id,
            "field": field,
            "parent_id": parent_id,
            "body_md": body_md,
        }
        return dict(self.ok(self.post("/api/comments", body), 201)["comment"])

    def list(self, entity_type: str, **params: Any) -> dict[str, Any]:
        """One page of a list."""
        return self.ok(self.get(f"/api/entities/{entity_type}", params))


# --------------------------------------------------------------------------------------
# Direct ASGI calls
# --------------------------------------------------------------------------------------


@dataclass
class AsgiResult:
    """The response of a direct ASGI call."""

    status: int
    body: bytes


def call_asgi(app: FastAPI, method: str, path: str) -> AsgiResult:
    """Call the ASGI app with a hand-made scope. ``path`` is the decoded path, as an ASGI
    server passes it (``/%2e%2e/x`` arrives as ``/../x``)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", HOST.encode("latin-1"))],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8080),
        "state": {},
    }
    messages: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    async def call() -> None:
        await app(scope, receive, send)

    anyio.run(call)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return AsgiResult(start["status"], content)
