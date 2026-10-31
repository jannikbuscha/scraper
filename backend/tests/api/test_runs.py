"""Collector and run endpoints (docs/API.md §7.2) and raw snapshots (§7.3), with
``COLLECTOR_RUN_INLINE`` and the replay transport (docs/COLLECTORS.md §12.1)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from mdt.app import StartupError, create_app
from mdt.collectors import registry
from mdt.collectors.base import RunContext
from mdt.config import Settings
from tests.api.conftest import api_settings
from tests.api.helpers import BASE_URL, ApiClient, error_of
from tests.collectors.stubs import StubCollector, write_sources
from tests.conftest import Db

TEST_EMAIL = "ua-test@mdt-portfolio.internal"
FIXTURE_TIME = "2026-10-29T12:00:00.000000Z"


def replay_dir(root: Path) -> Path:
    """Synthetic fixtures served by the replay transport."""
    directory = root / "replay"
    directory.mkdir()
    pages = {
        "listing": ("https://example.org/listing", b"<html><h1>Example listing</h1></html>"),
        "item": ("https://example.org/item", b"<html><h1>Example item</h1></html>"),
    }
    for name, (url, body) in pages.items():
        (directory / f"{name}.html").write_bytes(body)
        meta = {
            "fixture": name,
            "body": f"{name}.html",
            "url": url,
            "final_url": url,
            "redirects": [],
            "status": 200,
            "retrieved_at": FIXTURE_TIME,
            "content_type": "text/html; charset=utf-8",
            "headers": {"content-type": "text/html; charset=utf-8"},
        }
        (directory / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


def crawl(ctx: RunContext) -> None:
    """Fetch the listing, an item and a URL without a fixture."""
    for path in ("listing", "item", "missing"):
        ctx.client.get(f"https://example.org/{path}")
        ctx.count("pages_parsed")
    ctx.message("warning", "invalid_value", "synthetic warning", url="https://example.org/item")


@pytest.fixture
def stub() -> Iterator[StubCollector]:
    collector = StubCollector(behaviour=crawl)
    registry.register("stub", collector)
    registry.register("stub_builtin", StubCollector(NAME="stub_builtin", PARAMS=frozenset()))
    registry.register("stub_disabled", StubCollector(NAME="stub_disabled"))
    try:
        yield collector
    finally:
        for name in ("stub", "stub_builtin", "stub_disabled"):
            registry.unregister(name)


def make_client(api_db: Db, tmp_path: Path, **overrides: Any) -> Iterator[ApiClient]:
    values: dict[str, Any] = {
        "sources_file": write_sources(tmp_path),
        "collector_run_inline": True,
        "collector_replay_dir": replay_dir(tmp_path),
        "contact_email": TEST_EMAIL,
        **overrides,
    }
    settings: Settings = api_settings(api_db.root, **values)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        yield ApiClient(client)


@pytest.fixture
def client(api_db: Db, tmp_path: Path, stub: StubCollector) -> Iterator[ApiClient]:
    yield from make_client(api_db, tmp_path)


def insert_running_run(api_db: Db, run_id: str, heartbeat: str) -> None:
    with api_db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO collector_run (id, collector, trigger, mode, status, started_at,"
                " heartbeat_at, code_version, config_hash) VALUES (:id, 'stub', 'cli',"
                " 'incremental', 'running', :at, :at, '0.0.0', 'hash')"
            ),
            {"id": run_id, "at": heartbeat},
        )


# --------------------------------------------------------------------------------------
# Collectors
# --------------------------------------------------------------------------------------


def test_collectors_lists_configured_and_implemented_collectors(client: ApiClient) -> None:
    collectors = client.ok(client.get("/api/collectors"))["collectors"]
    by_name = {collector["name"]: collector for collector in collectors}
    assert list(by_name) == ["stub", "stub_disabled", "stub_builtin"]  # not stub_unimplemented
    stub = by_name["stub"]
    assert stub["label"] == "Stub collector" and stub["source"] == "S0"
    assert stub["available"] is True and stub["unavailable_reason"] is None
    assert stub["modes"] == ["incremental", "full"] and stub["params"] == ["limit", "refetch"]
    assert stub["hosts"] == [{"host": "slow.example.org", "min_interval_s": 5.0}]
    assert stub["exclude_hosts"] == ["excluded.example.org"]
    assert stub["licence"] == {"code": "unknown", "statement": None}
    assert stub["declaration"] == {
        "document": {
            "creates": True,
            "writes": ["title"],
            "propose_only": [],
            "discontinued": False,
        }
    }
    assert stub["last_run"] is None and stub["running_run_id"] is None
    assert stub["observations"] == {"total": 0, "present": 0, "missing": 0}
    assert stub["open_proposals"] == 0 and stub["needs_server_check"] is False
    disabled = by_name["stub_disabled"]
    assert disabled["available"] is False and disabled["unavailable_reason"] == "disabled"
    assert by_name["stub_builtin"]["builtin"] is True


def test_replay_mode_makes_collectors_available_without_a_contact_address(
    api_db: Db, tmp_path: Path, stub: StubCollector
) -> None:
    for client in make_client(api_db, tmp_path, contact_email=None):
        collectors = client.ok(client.get("/api/collectors"))["collectors"]
        assert {c["name"]: c["available"] for c in collectors}["stub"] is True


@pytest.mark.parametrize("email", [None, "research-contact@example.org"])
def test_without_a_usable_contact_address_network_collectors_are_unavailable(
    api_db: Db, tmp_path: Path, stub: StubCollector, email: str | None
) -> None:
    for client in make_client(api_db, tmp_path, contact_email=email, collector_replay_dir=None):
        collectors = {c["name"]: c for c in client.ok(client.get("/api/collectors"))["collectors"]}
        assert collectors["stub"]["unavailable_reason"] == "contact_email_missing"
        assert collectors["stub_builtin"]["available"] is True  # no network
        response = client.post("/api/runs", {"collector": "stub"})
        assert response.status_code == 409
        error = error_of(response)
        assert error["code"] == "collector_unavailable"
        assert error["details"] == {"reason": "contact_email_missing"}
        assert email is None or email not in response.text


def test_collector_detail_with_recent_runs(client: ApiClient) -> None:
    run = client.ok(client.post("/api/runs", {"collector": "stub"}), 202)["run"]
    detail = client.ok(client.get("/api/collectors/stub"))
    assert detail["collector"]["last_run"]["id"] == run["id"]
    assert [item["id"] for item in detail["recent_runs"]] == [run["id"]]
    assert error_of(client.get("/api/collectors/stub_unimplemented"))["code"] == "not_found"
    assert client.get("/api/collectors/nonexistent").status_code == 404


# --------------------------------------------------------------------------------------
# Starting runs
# --------------------------------------------------------------------------------------


def test_post_run_executes_inline_with_the_replay_transport(client: ApiClient) -> None:
    response = client.post("/api/runs", {"collector": "stub", "mode": "full", "params": {}})
    run = client.ok(response, 202)["run"]
    assert run["status"] == "partial"  # the URL without a fixture was refused
    assert (run["collector"], run["collector_label"], run["trigger"], run["mode"]) == (
        "stub",
        "Stub collector",
        "ui",
        "full",
    )
    assert run["params"] == {"replay": True}
    assert run["stats"]["requests"] == 3 and run["stats"]["snapshots"] == 2
    assert run["stats"]["pages_parsed"] == 3
    assert run["message_counts"] == {"error": 1, "warning": 1, "info": 0}
    assert run["finished_at"] and run["duration_s"] >= 0 and run["error"] is None
    assert run["complete_listing"] is False and run["cancel_requested_at"] is None
    assert run["code_version"] and len(run["config_hash"]) == 64

    fetches = client.ok(client.get(f"/api/runs/{run['id']}/fetches"))
    assert [(item["url"], item["outcome"]) for item in fetches["items"]] == [
        ("https://example.org/robots.txt", "ok"),
        ("https://example.org/listing", "ok"),
        ("https://example.org/item", "ok"),
        ("https://example.org/missing", "refused"),
    ]
    refused = client.ok(client.get(f"/api/runs/{run['id']}/fetches", {"outcome": "refused"}))
    assert refused["total"] == 1 and refused["items"][0]["error"] == "no fixture"
    content = client.ok(client.get(f"/api/runs/{run['id']}/fetches", {"purpose": "content"}))
    assert content["total"] == 3
    messages = client.ok(client.get(f"/api/runs/{run['id']}/messages"))
    assert [(item["level"], item["code"]) for item in messages["items"]] == [
        ("error", "http_error"),
        ("warning", "invalid_value"),
    ]
    assert messages["refs"] == {}
    errors = client.ok(client.get(f"/api/runs/{run['id']}/messages", {"level": "error"}))
    assert errors["total"] == 1 and errors["items"][0]["details"]["outcome"] == "refused"


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ({"collector": "stub", "mode": "weekly"}, "mode"),
        ({"collector": "stub", "params": {"speed": 1}}, "params.speed"),
        ({"collector": "stub", "params": {"document_ids": []}}, "params.document_ids"),
        ({"collector": "stub", "params": {"limit": 0}}, "params.limit"),
        ({"collector": "stub", "extra": True}, "extra"),
        ({"mode": "full"}, "collector"),
    ],
)
def test_post_run_validation(client: ApiClient, body: dict[str, Any], path: str) -> None:
    response = client.post("/api/runs", body)
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_error" and path in error["details"]


def test_post_run_unknown_disabled_and_in_progress(client: ApiClient, api_db: Db) -> None:
    assert client.post("/api/runs", {"collector": "nonexistent"}).status_code == 404
    assert client.post("/api/runs", {"collector": "stub_unimplemented"}).status_code == 404
    disabled = client.post("/api/runs", {"collector": "stub_disabled"})
    assert disabled.status_code == 409
    assert error_of(disabled)["details"] == {"reason": "disabled"}
    insert_running_run(api_db, "run_01JBX3RXNNNNG0000000000000", "2999-01-01T00:00:00.000000Z")
    busy = client.post("/api/runs", {"collector": "stub"})
    assert busy.status_code == 409
    assert error_of(busy) == {
        "code": "run_in_progress",
        "message": "Run run_01JBX3RXNNNNG0000000000000 (stub) is running; try again when it has"
        " finished",
        "details": {"run_id": "run_01JBX3RXNNNNG0000000000000"},
    }


def test_a_stale_run_is_recovered_as_failed(client: ApiClient, api_db: Db) -> None:
    insert_running_run(api_db, "run_01JBX3STA1E0000000000000A", "2026-01-01T00:00:00.000000Z")
    run = client.ok(client.post("/api/runs", {"collector": "stub_builtin"}), 202)["run"]
    assert run["status"] == "succeeded"
    stale = client.ok(client.get("/api/runs/run_01JBX3STA1E0000000000000A"))["run"]
    assert stale["status"] == "failed"
    assert stale["error"].startswith("interrupted: no heartbeat since 2026-01-01")


def test_stale_runs_are_recovered_at_startup(
    api_db: Db, tmp_path: Path, stub: StubCollector
) -> None:
    insert_running_run(api_db, "run_01JBX3STA1E0000000000000B", "2026-01-01T00:00:00.000000Z")
    for client in make_client(api_db, tmp_path):
        run = client.ok(client.get("/api/runs/run_01JBX3STA1E0000000000000B"))["run"]
        assert run["status"] == "failed"


# --------------------------------------------------------------------------------------
# Listing, detail and cancel
# --------------------------------------------------------------------------------------


def test_runs_list_filters_and_pages(client: ApiClient) -> None:
    first = client.ok(client.post("/api/runs", {"collector": "stub"}), 202)["run"]
    second = client.ok(client.post("/api/runs", {"collector": "stub_builtin"}), 202)["run"]
    listing = client.ok(client.get("/api/runs"))
    assert [item["id"] for item in listing["items"]] == [second["id"], first["id"]]
    assert (listing["total"], listing["page"], listing["page_size"]) == (2, 1, 50)
    only = client.ok(client.get("/api/runs", {"collector": "stub", "status": "partial,failed"}))
    assert [item["id"] for item in only["items"]] == [first["id"]]
    page = client.ok(client.get("/api/runs", {"page": 2, "page_size": 1}))
    assert [item["id"] for item in page["items"]] == [first["id"]]
    assert client.ok(client.get("/api/runs", {"trigger": "cli"}))["total"] == 0
    for params in ({"status": "done"}, {"collector": "unknown"}, {"page_size": 501}):
        response = client.get("/api/runs", params)
        assert response.status_code == 400 and error_of(response)["code"] == "validation_error"
    assert client.get("/api/runs/run_missing").status_code == 404
    assert client.get("/api/runs/run_missing/fetches").status_code == 404
    assert client.get("/api/runs/run_missing/messages").status_code == 404


def test_cancel(client: ApiClient, api_db: Db) -> None:
    insert_running_run(api_db, "run_01JBX3CANCE10000000000000", "2999-01-01T00:00:00.000000Z")
    cancelled = client.ok(client.post("/api/runs/run_01JBX3CANCE10000000000000/cancel", {}))
    assert cancelled["run"]["status"] == "running"
    assert cancelled["run"]["cancel_requested_at"] is not None
    with api_db.engine.begin() as connection:
        connection.execute(text("UPDATE collector_run SET status = 'cancelled'"))
    finished = client.post("/api/runs/run_01JBX3CANCE10000000000000/cancel", {})
    assert finished.status_code == 409
    assert error_of(finished) == {
        "code": "invalid_state",
        "message": "Only a running run can be cancelled",
        "details": {"state": "cancelled"},
    }
    assert client.post("/api/runs/run_missing/cancel", {}).status_code == 404
    assert client.post("/api/runs/run_missing/cancel", {"x": 1}).status_code == 400


# --------------------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------------------


def test_snapshot_metadata_and_body(client: ApiClient) -> None:
    run = client.ok(client.post("/api/runs", {"collector": "stub"}), 202)["run"]
    fetches = client.ok(client.get(f"/api/runs/{run['id']}/fetches", {"outcome": "ok"}))
    raw_id = next(
        item["raw_snapshot_id"] for item in fetches["items"] if item["purpose"] == "content"
    )
    snapshot = client.ok(client.get(f"/api/snapshots/{raw_id}"))["snapshot"]
    assert snapshot["id"] == raw_id and snapshot["run_id"] == run["id"]
    assert (snapshot["via"], snapshot["source_id"], snapshot["fetched_at"]) == (
        "replay",
        "stub",
        FIXTURE_TIME,
    )
    assert snapshot["url"] == "https://example.org/listing"
    assert snapshot["content_type"] == "text/html" and snapshot["http_status"] == 200
    assert set(snapshot) == {
        "id", "run_id", "source_id", "via", "url", "final_url", "redirects", "http_status",
        "fetched_at", "headers", "content_type", "filename", "sha256", "size",
    }  # fmt: skip
    body = client.get(f"/api/snapshots/{raw_id}/body")
    assert body.status_code == 200
    assert body.content == b"<html><h1>Example listing</h1></html>"
    assert body.headers["content-type"].startswith("text/html")
    assert body.headers["content-disposition"].startswith(f'attachment; filename="{raw_id}.')
    assert body.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert client.get("/api/snapshots/raw_missing").status_code == 404
    assert client.get("/api/snapshots/raw_missing/body").status_code == 404


def test_an_invalid_sources_file_stops_startup(api_db: Db, tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: 2\ncollectors: {}\n", encoding="utf-8")
    with pytest.raises(StartupError, match=r"sources: broken\.yaml: version must be 1"):
        create_app(api_settings(api_db.root, sources_file=broken))
    with pytest.raises(StartupError, match="is missing"):
        create_app(api_settings(api_db.root, sources_file=tmp_path / "absent.yaml"))
