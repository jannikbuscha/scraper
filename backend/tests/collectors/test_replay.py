"""The replay transport (docs/COLLECTORS.md §4.10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from mdt.collectors.fetchlog import MemorySink
from mdt.collectors.replay import (
    REPLAY_EXTENSION,
    ReplayIndexError,
    ReplayMiss,
    ReplayTransport,
    build_index,
)
from tests.collectors.conftest import FIXTURES, make_client


def write_fixture(directory: Path, name: str, url: str, body: bytes, **meta: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.html").write_bytes(body)
    data = {
        "fixture": name,
        "body": f"{name}.html",
        "url": url,
        "final_url": meta.pop("final_url", url),
        "redirects": meta.pop("redirects", []),
        "status": meta.pop("status", 200),
        "retrieved_at": meta.pop("retrieved_at", "2026-10-29T12:00:00.000000Z"),
        "content_type": meta.pop("content_type", "text/html; charset=utf-8"),
        "headers": meta.pop("headers", {}),
        **meta,
    }
    (directory / f"{name}.meta.json").write_text(json.dumps(data), encoding="utf-8")


def get(transport: ReplayTransport, url: str) -> httpx2.Response:
    with httpx2.Client(transport=transport, follow_redirects=False) as client:
        return client.get(url)


def test_index_of_a_collector_directory() -> None:
    index = build_index([FIXTURES / "ministry_projects"])
    assert index["https://thedigital.gov.ua/projects"].fixture == "projects_page1"
    assert index["https://thedigital.gov.ua/projects/page/2"].fixture == "projects_page2"
    # A redirect fixture answers its hop with a bodiless redirect and registers its final URL.
    hop = index["https://thedigital.gov.ua/projects/technologies/winwin"]
    assert hop.status == 302 and hop.body_path is None
    assert hop.headers["location"] == "https://winwin.gov.ua/"
    assert index["https://winwin.gov.ua/"].fixture == "link_entry_winwin_redirect"
    # variant_* fixtures are not indexed.
    assert all(not entry.fixture.startswith("variant_") for entry in index.values())


def test_refetch_fixtures_are_not_indexed_so_duplicate_urls_do_not_clash() -> None:
    index = build_index([FIXTURES / "kmu_news"])
    url = (
        "https://www.kmu.gov.ua/en/news/"
        "uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"
    )
    assert index[url].fixture == "news_en_2019_regulation"


def test_the_seed_url_of_winwin_is_answered_by_its_final_url_fixture() -> None:
    transport = ReplayTransport([FIXTURES / "project_sites"])
    response = get(transport, "https://winwin.gov.ua")
    assert response.status_code == 200
    assert response.extensions[REPLAY_EXTENSION]["fixture"] == "winwin_home_csr_shell"


def test_two_fixtures_with_the_same_key_fail(tmp_path: Path) -> None:
    write_fixture(tmp_path, "first", "https://example.org/a", b"one")
    write_fixture(tmp_path, "second", "https://EXAMPLE.org/a#fragment", b"two")
    with pytest.raises(ReplayIndexError, match="first and second both answer"):
        build_index([tmp_path])


def test_a_final_url_does_not_shadow_another_fixture(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        "a_redirect",
        "https://example.org/old",
        b"redirect target body",
        redirects=["301 https://example.org/new"],
        final_url="https://example.org/new",
    )
    write_fixture(tmp_path, "b_direct", "https://example.org/new", b"direct body")
    transport = ReplayTransport([tmp_path])
    assert get(transport, "https://example.org/new").content == b"direct body"
    old = get(transport, "https://example.org/old")
    assert old.status_code == 301 and old.headers["location"] == "https://example.org/new"


def test_responses_carry_the_fixture_time_and_drop_body_headers(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        "page",
        "https://example.org/page?x=1",
        b"<html>Example</html>",
        retrieved_at="2026-10-29T13:00:00.000000Z",
        headers={"Content-Encoding": "gzip", "Content-Length": "999", "ETag": '"v1"'},
    )
    transport = ReplayTransport([tmp_path])
    response = get(transport, "https://example.org/page?x=1")
    assert response.content == b"<html>Example</html>"
    assert response.headers["etag"] == '"v1"'
    assert "content-encoding" not in response.headers
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.extensions[REPLAY_EXTENSION] == {
        "fixture": "page",
        "retrieved_at": "2026-10-29T13:00:00.000000Z",
    }
    with pytest.raises(ReplayMiss):
        get(transport, "https://example.org/page?x=2")  # the query string is exact
    assert get(transport, "https://example.org/robots.txt").status_code == 404


def test_client_stores_replayed_responses_as_replay_snapshots(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        "page",
        "https://example.org/page",
        b"<html>Example</html>",
        retrieved_at="2026-10-29T13:00:00.000000Z",
    )
    sink = MemorySink()
    client = make_client(ReplayTransport([tmp_path]), sink=sink, replay=True)
    result = client.get("https://example.org/page")
    assert result.ok and result.snapshot is not None
    assert result.snapshot.via == "replay"
    assert result.snapshot.fetched_at == "2026-10-29T13:00:00.000000Z"
    missing = client.get("https://example.org/missing")
    assert missing.outcome == "refused" and missing.error == "no fixture"
    assert [entry.outcome for entry in sink.fetches] == ["ok", "ok", "refused"]
    assert sink.fetches[0].url == "https://example.org/robots.txt"  # a 404 answer: allow all
    assert client.clock.sleeps == []  # type: ignore[attr-defined]
