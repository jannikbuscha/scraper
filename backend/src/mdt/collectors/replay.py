"""Replay transport (docs/COLLECTORS.md §4.10): an httpx2 transport that answers requests
from the fixtures in ``backend/tests/fixtures/<collector>/`` instead of the network.

* **Index:** the fixtures of the given directories (not recursive), keyed by the normalised
  ``meta.url`` (docs/COLLECTORS.md §4.1; the query string exact). A fixture whose
  ``meta.redirects`` is not empty answers its hop URLs with bodiless redirect responses
  (``Location`` header) and also registers its ``final_url``, unless another fixture has
  that URL. Fixtures named ``*_refetch`` or ``variant_*`` are not indexed; two indexed
  fixtures with the same key fail when the index is built.
* A URL without a fixture raises :class:`ReplayMiss`, which the client records as
  ``refused`` (``error = "no fixture"``); a missing robots.txt fixture is a 404.
* Every response carries the extension :data:`REPLAY_EXTENSION` with the fixture's name and
  ``retrieved_at``, which the client stores as the snapshot's ``fetched_at`` with
  ``via = replay``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from mdt.collectors.urls import UrlError, parse_fetch_url

#: Response extension set on every replayed response: ``{"fixture", "retrieved_at"}``.
REPLAY_EXTENSION = "mdt_replay"
#: Original response headers that do not describe the stored body (it is decoded and may
#: be an excerpt), so they are not replayed.
_DROPPED_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class ReplayMiss(Exception):
    """No fixture answers the URL."""

    def __init__(self, url: str) -> None:
        super().__init__(f"no fixture for {url}")
        self.url = url


class ReplayIndexError(ValueError):
    """The fixtures cannot be indexed (unreadable meta file, duplicate key)."""


@dataclass(frozen=True)
class ReplayEntry:
    """How the transport answers one URL."""

    fixture: str
    status: int
    headers: Mapping[str, str]
    retrieved_at: str
    body_path: Path | None = None  # None: a bodiless redirect


def _key(url: str, where: str) -> str:
    try:
        return parse_fetch_url(url).url
    except UrlError as exc:
        raise ReplayIndexError(f"{where}: invalid URL {url!r}") from exc


def _headers(meta: Mapping[str, Any]) -> dict[str, str]:
    headers = {
        str(name).lower(): str(value)
        for name, value in (meta.get("headers") or {}).items()
        if str(name).lower() not in _DROPPED_HEADERS
    }
    content_type = meta.get("content_type")
    if "content-type" not in headers and content_type and "assumed" not in str(content_type):
        headers["content-type"] = str(content_type)
    return headers


def _hop(text: str, where: str) -> tuple[int, str]:
    status, _, target = str(text).partition(" ")
    if not status.isdigit() or not target:
        raise ReplayIndexError(f"{where}: invalid redirect {text!r}")
    return int(status), target.strip()


def build_index(directories: Iterable[Path]) -> dict[str, ReplayEntry]:
    """The URL index of the fixtures in ``directories`` (see the module docstring)."""
    index: dict[str, ReplayEntry] = {}
    owners: dict[str, str] = {}
    finals: list[tuple[str, ReplayEntry]] = []

    def add(key: str, entry: ReplayEntry) -> None:
        if key in index:
            raise ReplayIndexError(f"fixtures {owners[key]} and {entry.fixture} both answer {key}")
        index[key] = entry
        owners[key] = entry.fixture

    for directory in directories:
        for meta_path in sorted(directory.glob("*.meta.json")):
            where = meta_path.name
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                name = str(meta["fixture"])
                status = int(meta["status"])
                retrieved_at = str(meta["retrieved_at"])
                body_path = directory / str(meta["body"])
                url = str(meta["url"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ReplayIndexError(f"{where}: not a fixture meta file") from exc
            if name.endswith("_refetch") or name.startswith("variant_"):
                continue
            response = ReplayEntry(name, status, _headers(meta), retrieved_at, body_path)
            redirects = meta.get("redirects") or []
            if not redirects:
                add(_key(url, where), response)
                continue
            current = _key(url, where)
            for text in redirects:
                hop_status, target = _hop(text, where)
                add(current, ReplayEntry(name, hop_status, {"location": target}, retrieved_at))
                current = _key(target, where)
            finals.append((_key(str(meta.get("final_url") or current), where), response))
    for key, entry in finals:
        if key not in index:
            index[key] = entry
            owners[key] = entry.fixture
    return index


class ReplayTransport(httpx2.BaseTransport):
    """Answers requests from fixtures; nothing leaves the machine."""

    def __init__(self, directories: Iterable[Path]) -> None:
        self.directories = tuple(directories)
        self.index = build_index(self.directories)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        """The fixture response for the request's URL (raises :class:`ReplayMiss`)."""
        url = parse_fetch_url(str(request.url))
        entry = self.index.get(url.url)
        if entry is None:
            if url.path == "/robots.txt":
                return httpx2.Response(404, extensions={REPLAY_EXTENSION: {"fixture": None}})
            raise ReplayMiss(url.url)
        body = b"" if entry.body_path is None else entry.body_path.read_bytes()
        return httpx2.Response(
            entry.status,
            headers=dict(entry.headers),
            content=body,
            extensions={
                REPLAY_EXTENSION: {"fixture": entry.fixture, "retrieved_at": entry.retrieved_at}
            },
        )
