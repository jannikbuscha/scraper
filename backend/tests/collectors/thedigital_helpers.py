"""Helpers of the parser tests of the thedigital.gov.ua collectors (C1, C4): snapshots of
the fixtures (no database, no network) and synthetic pages.

:func:`turbo_stream` encodes a Python value the way thedigital.gov.ua embeds its loader data
(React Router turbo-stream, docs/COLLECTORS.md §7.2), so tests can build synthetic pages
with obviously synthetic values (example.org, "Example project")."""

from __future__ import annotations

import json
from typing import Any

from mdt.collectors.base import Snapshot
from tests.collectors.conftest import FIXTURES

#: The snapshot ID every fixture snapshot gets unless a test asks for another one.
RAW_ID = "raw_fixture"
NULL = -5


def fixture_meta(collector: str, name: str) -> dict[str, Any]:
    """The meta file of a fixture (``name`` without extension)."""
    data = json.loads((FIXTURES / collector / f"{name}.meta.json").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def fixture_snapshot(
    collector: str, name: str, *, body: bytes | None = None, raw_snapshot_id: str = RAW_ID
) -> Snapshot:
    """A snapshot of the fixture ``name`` as the store would hand it to a parser (the
    body may be replaced, e.g. by a derived variant)."""
    meta = fixture_meta(collector, name)
    content = body if body is not None else (FIXTURES / collector / meta["body"]).read_bytes()
    content_type = (meta.get("content_type") or "").split(";")[0].strip().lower() or None
    return Snapshot(
        raw_snapshot_id=raw_snapshot_id,
        run_id=None,
        source_id=collector,
        via="replay",
        url=meta["url"],
        final_url=meta["final_url"],
        redirects=tuple(meta["redirects"]),
        http_status=meta["status"],
        fetched_at=meta["retrieved_at"],
        headers=dict(meta["headers"]),
        content_type=content_type,
        filename=None,
        sha256=meta["sha256_stored"],
        size=len(content),
        body=content,
    )


def fixture_text(collector: str, name: str) -> str:
    """The body of a fixture as text (``name`` without extension)."""
    meta = fixture_meta(collector, name)
    return (FIXTURES / collector / meta["body"]).read_text("utf-8")


def turbo_stream(value: dict[str, Any]) -> str:
    """``value`` as a one-line turbo-stream: values referenced by index, objects as
    ``{"_<key index>": <value index>}``, null as the constant -5."""
    values: list[Any] = []

    def ref(item: Any) -> int:
        if item is None:
            return NULL
        index = len(values)
        values.append(None)
        if isinstance(item, dict):
            values[index] = {f"_{ref(key)}": ref(entry) for key, entry in item.items()}
        elif isinstance(item, list):
            values[index] = [ref(entry) for entry in item]
        else:
            values[index] = item
        return index

    ref(value)
    return json.dumps(values, ensure_ascii=False)


def synthetic_page(
    url: str, route: str, data: dict[str, Any], *, status: int = 200, raw_snapshot_id: str = RAW_ID
) -> Snapshot:
    """A synthetic HTML page that embeds ``data`` as the loader data of ``route`` (and an
    empty ``root`` entry), the way thedigital.gov.ua does."""
    stream = turbo_stream({"loaderData": {"root": {}, route: data}})
    literal = json.dumps(stream, ensure_ascii=False)
    html = (
        "<!DOCTYPE html><html><head><title>Example page</title></head><body>"
        "<main>Example page</main>"
        f"<script>window.__reactRouterContext.streamController.enqueue({literal});</script>"
        "</body></html>"
    )
    body = html.encode("utf-8")
    return Snapshot(
        raw_snapshot_id=raw_snapshot_id,
        run_id=None,
        source_id="example",
        via="replay",
        url=url,
        final_url=url,
        redirects=(),
        http_status=status,
        fetched_at="2026-01-01T00:00:00.000000Z",
        headers={"content-type": "text/html; charset=utf-8"},
        content_type="text/html",
        filename=None,
        sha256="0" * 64,
        size=len(body),
        body=body,
    )
