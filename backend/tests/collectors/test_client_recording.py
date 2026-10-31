"""Recording of the polite client in the database (docs/COLLECTORS.md §4.8, §4.9):
one ``fetch_log`` row per attempt, every final response body stored as a raw snapshot
before the collector sees it, conditional requests from earlier live snapshots."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import select

from mdt.collectors.client import manual_fetch_client
from mdt.collectors.errors import CollectorUnavailableError
from mdt.collectors.fetchlog import DatabaseSink
from mdt.collectors.sources import load_sources
from mdt.collectors.store import SnapshotMeta, SnapshotStore
from mdt.collectors.throttle import HostThrottle
from mdt.config import REPO_ROOT, Settings
from mdt.db.models import FetchLog, RawSnapshot
from tests.collectors.conftest import FIXTURES, TEST_EMAIL, FakeClock, Site, make_client
from tests.conftest import Db


def sink_for(db: Db) -> tuple[DatabaseSink, SnapshotStore]:
    store = SnapshotStore(db.settings.raw_path)
    session = db.session()
    return DatabaseSink(session, store, run_id=None), store


def test_one_fetch_log_row_per_attempt_and_stored_bodies(db: Db) -> None:
    body = "<html>Синтетична сторінка</html>".encode()
    site = Site({"https://example.org/page": [503, httpx2.Response(200, content=body)]})
    sink, store = sink_for(db)
    client = make_client(site, sink=sink, clock=FakeClock())
    result = client.get("https://example.org/page")
    sink.session.close()
    assert result.ok and result.snapshot is not None
    with db.session() as session:
        rows = session.scalars(select(FetchLog).order_by(FetchLog.id)).all()
        assert [(row.purpose, row.outcome, row.attempt, row.status) for row in rows] == [
            ("robots", "ok", 1, 404),
            ("content", "http_error", 1, 503),
            ("content", "ok", 2, 200),
        ]
        assert all(row.run_id is None and row.host == "example.org" for row in rows)
        assert rows[2].raw_snapshot_id == result.snapshot.raw_snapshot_id
        assert rows[2].bytes == len(body)
        snapshot = session.get(RawSnapshot, result.snapshot.raw_snapshot_id)
        assert snapshot is not None
        assert snapshot.sha256 == hashlib.sha256(body).hexdigest()
        assert (snapshot.via, snapshot.source_id, snapshot.http_status) == ("live", "example", 200)
    assert store.read_body(result.snapshot.sha256) == body


def test_conditional_get_reuses_the_earlier_snapshot(db: Db) -> None:
    url = "https://example.org/microsite"
    store = SnapshotStore(db.settings.raw_path)
    with db.session() as session:
        earlier = store.put(
            session,
            b"<html>earlier</html>",
            SnapshotMeta(
                source_id="example",
                via="live",
                url=url,
                final_url=url,
                http_status=200,
                headers={"ETag": '"v1"', "Last-Modified": "Wed, 01 Oct 2026 10:00:00 GMT"},
            ),
        )

    def not_modified(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["if-none-match"] == '"v1"'
        assert request.headers["if-modified-since"] == "Wed, 01 Oct 2026 10:00:00 GMT"
        return httpx2.Response(304)

    site = Site({url: not_modified})
    sink, _ = sink_for(db)
    client = make_client(site, sink=sink)
    result = client.get(url)
    sink.session.close()
    assert result.outcome == "not_modified" and result.ok
    assert result.snapshot is not None
    assert result.snapshot.raw_snapshot_id == earlier.raw_snapshot_id
    assert result.snapshot.body == b"<html>earlier</html>"
    with db.session() as session:
        row = session.scalars(select(FetchLog).where(FetchLog.url == url)).one()
        assert (row.outcome, row.status, row.raw_snapshot_id) == (
            "not_modified",
            304,
            earlier.raw_snapshot_id,
        )
        assert len(session.scalars(select(RawSnapshot)).all()) == 1  # nothing new stored


def test_no_conditional_request_without_validators_or_in_replay(db: Db) -> None:
    url = "https://example.org/plain"
    store = SnapshotStore(db.settings.raw_path)
    with db.session() as session:
        store.put(
            session,
            b"no validators",
            SnapshotMeta(source_id="example", via="live", url=url, final_url=url, http_status=200),
        )
    site = Site({url: "fresh"})
    sink, _ = sink_for(db)
    client = make_client(site, sink=sink)
    result = client.get(url)
    sink.session.close()
    assert result.outcome == "ok"
    assert "if-none-match" not in site.requests[-1].headers


def manual_settings(db: Db, tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "sources_file": REPO_ROOT / "sources.yaml",
        "contact_email": TEST_EMAIL,
        **overrides,
    }
    return db.settings.model_copy(update=values)


def test_a_manual_fetch_is_recorded_without_a_run(db: Db, tmp_path: Path) -> None:
    site = Site({"https://example.org/report": httpx2.Response(200, content=b"%PDF-1.4 x")})
    settings = manual_settings(db, tmp_path)
    with db.session() as session:
        client = manual_fetch_client(
            session,
            settings,
            transport=httpx2.MockTransport(site),
            clock=FakeClock(),
            throttle=HostThrottle(),
        )
        result = client.get("https://example.org/report")
        client.close()
    assert result.ok and result.snapshot is not None
    assert (result.snapshot.source_id, result.snapshot.run_id, result.snapshot.via) == (
        "manual",
        None,
        "live",
    )
    assert client.deadline is not None and client.listing_host is None
    assert TEST_EMAIL in client.user_agent
    with db.session() as session:
        rows = session.scalars(select(FetchLog)).all()
    assert [row.run_id for row in rows] == [None, None]


def test_a_manual_fetch_of_an_archive_capture_takes_its_via_from_the_final_url(
    db: Db, tmp_path: Path
) -> None:
    site = Site(
        {
            "https://web.archive.org/web/20200101000000id_/https://example.org/": httpx2.Response(
                302,
                headers={
                    "Location": "https://web.archive.org/web/20200102030405id_/https://example.org/"
                },
            ),
            "https://web.archive.org/web/20200102030405id_/https://example.org/": "archived",
        }
    )
    clock = FakeClock()
    with db.session() as session:
        client = manual_fetch_client(
            session,
            manual_settings(db, tmp_path),
            transport=httpx2.MockTransport(site),
            clock=clock,
        )
        result = client.get(
            "https://web.archive.org/web/20200101000000id_/https://example.org/",
            via_for=lambda url: "wayback:" + url.split("/web/", 1)[1][:14],
        )
        client.close()
    assert result.snapshot is not None and result.snapshot.via == "wayback:20200102030405"
    assert 5.0 in clock.sleeps  # the 5 s interval that sources.yaml sets for web.archive.org


def test_manual_fetches_need_a_contact_address_unless_replaying(db: Db, tmp_path: Path) -> None:
    settings = manual_settings(db, tmp_path, contact_email="research-contact@example.org")
    with db.session() as session:
        with pytest.raises(CollectorUnavailableError) as raised:
            manual_fetch_client(session, settings)
        assert raised.value.details == {"reason": "contact_email_missing"}
        replaying = settings.model_copy(
            update={"collector_replay_dir": FIXTURES / "ministry_projects"}
        )
        client = manual_fetch_client(session, replaying)
        assert client.replay and "mailto" not in client.user_agent
        client.close()


def test_the_manual_configuration_merges_host_intervals() -> None:
    sources = load_sources(REPO_ROOT / "sources.yaml")
    manual = sources.manual
    assert manual.name == "manual" and manual.min_interval("web.archive.org") == 5.0
    assert manual.min_interval("example.org") == 1.0
    assert "codeua.com" in manual.exclude_hosts


def test_a_manual_fetch_that_runs_out_of_time_is_throttled(db: Db, tmp_path: Path) -> None:
    site = Site(
        {"https://example.org/robots.txt": httpx2.Response(503, headers={"Retry-After": "59"})}
    )
    with db.session() as session:
        client = manual_fetch_client(
            session,
            manual_settings(db, tmp_path),
            transport=httpx2.MockTransport(site),
            clock=FakeClock(),
            throttle=HostThrottle(),
        )
        client.clock.advance(30)  # type: ignore[attr-defined]
        result = client.get("https://example.org/page")
        client.close()
    assert result.outcome == "refused" and result.reason == "throttled"
