"""The data acquisition commands of the ``mdt`` CLI (docs/COLLECTORS.md §11)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from typer.testing import CliRunner

from mdt import cli
from mdt.collectors import registry
from mdt.collectors.base import RunContext
from mdt.collectors.throttle import SystemClock
from mdt.config import get_settings
from tests import synthetic
from tests.collectors.conftest import TEST_EMAIL, Site
from tests.collectors.stubs import StubCollector, write_sources

runner = CliRunner()
FIXTURE_TIME = "2026-10-29T12:00:00.000000Z"


@pytest.fixture(autouse=True)
def instant_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI uses the real clock: its politeness waits pass at once in these tests."""
    monkeypatch.setattr(SystemClock, "sleep", lambda self, seconds, cancel: True)


def write_fixture(directory: Path, name: str, url: str, body: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
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
        "headers": {},
    }
    (directory / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def crawl(ctx: RunContext) -> None:
    for path in (ctx.params.get("refetch") and ("listing", "missing")) or ("listing",):
        ctx.client.get(f"https://example.org/{path}")
        ctx.count("pages_parsed")


@pytest.fixture
def environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Path]:
    data = tmp_path / "data"
    replay = tmp_path / "replay"
    write_fixture(replay, "listing", "https://example.org/listing", b"<html>listing</html>")
    variables = {
        "DATA_DIR": str(data),
        "DATABASE_URL": f"sqlite:///{data / 'app.db'}",
        "CODEBOOK_DIR": str(codebook_dir),
        "SEED_DIR": str(seed_dir),
        "FOCAL_ORG_SEED_KEY": synthetic.FOCAL_ORG_SEED_KEY,
        "SOURCES_FILE": str(write_sources(tmp_path)),
        "CONTACT_EMAIL": TEST_EMAIL,
        "COLLECTOR_REPLAY_DIR": str(replay),
        "PROJECT_URL": "",
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    registry.register("stub", StubCollector(behaviour=crawl))
    registry.register("stub_disabled", StubCollector(NAME="stub_disabled"))
    get_settings.cache_clear()
    assert invoke("db", "upgrade").exit_code == 0
    assert invoke("seed").exit_code == 0
    try:
        yield data
    finally:
        registry.unregister("stub")
        registry.unregister("stub_disabled")
        get_settings.cache_clear()


def invoke(*args: str) -> Any:
    return runner.invoke(cli.app, list(args))


def run_ids(output: str) -> list[str]:
    return [word for word in output.split() if word.startswith("run_")]


def test_collect_runs_a_collector_in_the_foreground(environment: Path) -> None:
    result = invoke("collect", "stub")
    assert result.exit_code == 0, result.output
    assert "(stub) started" in result.output
    assert ": succeeded after" in result.output and "[replay]" in result.output
    assert TEST_EMAIL not in result.output
    partial = invoke("collect", "stub", "--mode", "full", "--limit", "2", "--refetch")
    assert partial.exit_code == 2, partial.output  # the URL without a fixture
    assert ": partial after" in partial.output
    listing = invoke("runs")
    assert listing.exit_code == 0 and "2 of 2 runs" in listing.output
    filtered = invoke("runs", "--status", "partial")
    assert filtered.output.count("stub ") == 1
    run_id = run_ids(partial.output)[0]
    shown = invoke("runs", "show", run_id)
    assert shown.exit_code == 0, shown.output
    assert "http_error" in shown.output and "'limit': 2" in shown.output
    assert invoke("runs", "show", "run_missing").exit_code == 1


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("collect", "nonexistent"), "unknown collector nonexistent"),
        (("collect", "stub_unimplemented"), "unknown collector stub_unimplemented"),
        (("collect", "stub_disabled"), "is disabled"),
        (("collect", "stub", "--recall-sample", "3"), "params.recall_sample: not supported"),
        (("collect", "stub", "--mode", "weekly"), "mode: must be one of"),
    ],
)
def test_collect_refusals(environment: Path, args: tuple[str, ...], message: str) -> None:
    result = invoke(*args)
    assert result.exit_code == 1
    assert message in result.output


def test_collect_without_contact_address_outside_replay(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLECTOR_REPLAY_DIR", "")
    monkeypatch.setenv("CONTACT_EMAIL", "research-contact@example.org")
    get_settings.cache_clear()
    result = invoke("collect", "stub")
    assert result.exit_code == 1
    assert "error: CONTACT_EMAIL is not set" in result.output


def test_collect_while_another_run_is_running(environment: Path) -> None:
    connection = sqlite3.connect(environment / "app.db")
    try:
        connection.execute(
            "INSERT INTO collector_run (id, collector, trigger, mode, status, started_at,"
            " heartbeat_at, code_version, config_hash) VALUES ('run_01JBX3RXNNNNG0000000000000',"
            " 'stub', 'ui', 'incremental', 'running', '2999-01-01T00:00:00.000000Z',"
            " '2999-01-01T00:00:00.000000Z', '0', 'x')"
        )
        connection.commit()
    finally:
        connection.close()
    result = invoke("collect", "stub")
    assert result.exit_code == 1
    assert (
        "error: run run_01JBX3RXNNNNG0000000000000 (stub) is running; try again when it has"
        " finished" in result.output
    )


def test_check_reports_snapshot_files_and_triggers(environment: Path) -> None:
    assert invoke("collect", "stub").exit_code == 0
    assert invoke("check", "--deep").exit_code == 0
    files = sorted((environment / "raw").rglob("*.gz"))
    assert files
    files[0].unlink()
    result = invoke("check")
    assert result.exit_code == 1 and "is missing" in result.output
    connection = sqlite3.connect(environment / "app.db")
    try:
        connection.execute("DROP TRIGGER raw_snapshot_no_delete")
        connection.commit()
    finally:
        connection.close()
    result = invoke("check", "--deep")
    assert "raw_snapshot_no_delete on raw_snapshot is missing" in result.output


# --------------------------------------------------------------------------------------
# fixtures capture and sources check (MockTransport instead of the network)
# --------------------------------------------------------------------------------------


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Site:
    page = httpx2.Response(
        200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        content=b"<html><p>Synthetic page</p></html>",
    )
    site = Site({"https://example.org/page": page})
    monkeypatch.setattr(cli, "_transport", lambda: httpx2.MockTransport(site))
    return site


def test_fixtures_capture_writes_body_and_meta(
    environment: Path, site: Site, tmp_path: Path
) -> None:
    out = tmp_path / "captured"
    result = invoke("fixtures", "capture", "stub", "--out", str(out))
    assert result.exit_code == 0, result.output
    assert "stub_page: written (HTTP 200" in result.output
    meta = json.loads((out / "stub_page.meta.json").read_text(encoding="utf-8"))
    assert meta["body"] == "stub_page.html" and meta["url"] == "https://example.org/page"
    assert meta["trimmed"] is False and meta["sha256_original"] == meta["sha256_stored"]
    assert meta["collector"] == "stub" and meta["source"] == "S0" and meta["licence"] == "unknown"
    assert meta["capture"].startswith("mdt fixtures capture stub (app ")
    assert "user-agent" not in json.dumps(meta).lower() and TEST_EMAIL not in json.dumps(meta)
    assert (out / "stub_page.html").read_bytes() == b"<html><p>Synthetic page</p></html>"
    again = invoke("fixtures", "capture", "stub", "--out", str(out))
    assert "stub_page: kept" in again.output
    site.routes["https://example.org/page"] = "<p>Write to someone@mdt-portfolio.internal</p>"
    refused = invoke("fixtures", "capture", "stub", "--out", str(out), "--force")
    assert refused.exit_code == 1 and "contains an e-mail address" in refused.output
    assert invoke("fixtures", "capture", "stub", "--only", "nope", "--out", str(out)).exit_code == 1
    assert invoke("fixtures", "capture", "stub_builtin").exit_code == 1  # no fixtures list


def test_sources_check_reports_hosts(environment: Path, site: Site) -> None:
    site.routes["https://example.org/start"] = "start"
    result = invoke("sources", "check", "stub")
    assert result.exit_code == 0, result.output
    assert "example.org" in result.output and "slow.example.org" in result.output
    site.routes["https://slow.example.org/robots.txt"] = httpx2.Response(403, text="denied")
    blocked = invoke("sources", "check", "stub")
    assert blocked.exit_code == 1 and "blocked" in blocked.output
    assert invoke("sources", "check", "nonexistent").exit_code == 1
