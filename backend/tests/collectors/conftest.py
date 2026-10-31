"""Shared helpers of the collector framework tests.

Nothing here reaches the network: the autouse ``no_network`` guard of ``tests/conftest.py``
makes every real transport refuse requests to hosts other than the loopback interface (the
threaded local server tests), and the client tests use ``httpx2.MockTransport`` or the
replay transport.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest

from mdt.collectors.client import PoliteHttpClient
from mdt.collectors.fetchlog import FetchSink, MemorySink
from mdt.collectors.sources import CollectorConfig, parse_sources
from mdt.collectors.throttle import HostThrottle

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
#: Passes the CONTACT_EMAIL rule (not a reserved example domain) but reaches nobody.
TEST_EMAIL = "ua-test@mdt-portfolio.internal"
TEST_UA = f"MDT-Portfolio-Research/0.0-test (mailto:{TEST_EMAIL})"


def fixture_path(collector: str, name: str) -> Path:
    """A fixture body file, e.g. ``fixture_path("polite_client", "robots_kmu.txt")``."""
    return FIXTURES / collector / name


class FakeClock:
    """A clock whose waits pass instantly and are recorded."""

    def __init__(self, start: float = 1_000.0, wall: float = 1_800_000_000.0) -> None:
        self.start = start
        self.now = start
        self.wall = wall
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[float], None] | None = None

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.wall + (self.now - self.start)

    def sleep(self, seconds: float, cancel: threading.Event | None) -> bool:
        if self.on_sleep is not None:
            self.on_sleep(seconds)
        if cancel is not None and cancel.is_set():
            return False
        self.sleeps.append(round(seconds, 6))
        self.now += max(0.0, seconds)
        return True

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_config(**entry: Any) -> CollectorConfig:
    """A collector configuration from ``sources.yaml`` keys (collector ``example``);
    ``defaults`` may be passed as a mapping."""
    defaults = entry.pop("defaults", {})
    data = {
        "version": 1,
        "defaults": defaults,
        "collectors": {"example": {"label": "Example collector", **entry}},
    }
    return parse_sources(data, Path("sources.yaml")).collectors["example"]


Handler = Callable[[httpx2.Request], httpx2.Response]


def make_client(
    handler: Handler | httpx2.BaseTransport,
    *,
    config: CollectorConfig | None = None,
    sink: FetchSink | None = None,
    clock: FakeClock | None = None,
    **kwargs: Any,
) -> PoliteHttpClient:
    """A client on a mock transport with a fresh throttle and a fake clock."""
    transport = (
        handler if isinstance(handler, httpx2.BaseTransport) else httpx2.MockTransport(handler)
    )
    kwargs.setdefault("rng", random.Random(7))
    return PoliteHttpClient(
        config or make_config(),
        sink if sink is not None else MemorySink(),
        user_agent=TEST_UA,
        transport=transport,
        source_id="example",
        clock=clock or FakeClock(),
        throttle=HostThrottle(),
        **kwargs,
    )


class Site:
    """A scripted web site for MockTransport: routes map normalised URLs to responses or
    callables; every request is recorded. robots.txt defaults to 404 (allow all)."""

    def __init__(self, routes: dict[str, Any] | None = None, clock: FakeClock | None = None):
        self.routes: dict[str, Any] = dict(routes or {})
        self.requests: list[httpx2.Request] = []
        self.clock = clock
        self.duration = 0.0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.clock is not None and self.duration:
            self.clock.advance(self.duration)
        url = str(request.url)
        route = self.routes.get(url)
        if route is None:
            if request.url.path == "/robots.txt":
                return httpx2.Response(404)
            return httpx2.Response(404, text="not found")
        if callable(route):
            result = route(request)
            assert isinstance(result, httpx2.Response)
            return result
        if isinstance(route, list):
            item = route.pop(0) if len(route) > 1 else route[0]
            return _response(item)
        return _response(route)

    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]


def _response(item: Any) -> httpx2.Response:
    if isinstance(item, httpx2.Response):
        return httpx2.Response(item.status_code, headers=item.headers, content=item.content)
    if isinstance(item, int):
        return httpx2.Response(item, text=f"status {item}")
    if isinstance(item, bytes):
        return httpx2.Response(200, content=item)
    return httpx2.Response(200, text=str(item))


@pytest.fixture
def clock() -> Iterator[FakeClock]:
    yield FakeClock()
