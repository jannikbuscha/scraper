"""Fixtures of the document tests: a real network transport refuses every request."""

from __future__ import annotations

import httpx2
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests use MockTransport; a real transport raises."""

    def refuse(self: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"tests must not reach the network: {request.url}")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse)
