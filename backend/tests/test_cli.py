"""The ``mdt`` command-line interface."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mdt import cli
from mdt.config import get_settings
from tests import synthetic

runner = CliRunner()


@pytest.fixture
def environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Path]:
    """Settings through environment variables; the CLI runs from an unrelated directory."""
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{data / 'app.db'}")
    monkeypatch.setenv("CODEBOOK_DIR", str(codebook_dir))
    monkeypatch.setenv("SEED_DIR", str(seed_dir))
    monkeypatch.setenv("FOCAL_ORG_SEED_KEY", synthetic.FOCAL_ORG_SEED_KEY)
    monkeypatch.setenv("HOST", "127.0.0.2")
    monkeypatch.setenv("PORT", "8181")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()


def invoke(*args: str) -> Any:
    result = runner.invoke(cli.app, list(args))
    return result


def test_database_lifecycle(environment: Path) -> None:
    upgraded = invoke("db", "upgrade")
    assert upgraded.exit_code == 0, upgraded.output
    assert (environment / "app.db").is_file()
    assert "database is up to date" in upgraded.output
    dry = invoke("seed", "--dry-run")
    assert dry.exit_code == 0 and "would create" in dry.output
    seeded = invoke("seed")
    assert seeded.exit_code == 0, seeded.output
    assert "organization: create 1" in seeded.output
    again = invoke("seed")
    assert "revisions written: 0" in again.output
    checked = invoke("check")
    assert checked.exit_code == 0 and "no problems found" in checked.output
    recomputed = invoke("recompute")
    assert recomputed.exit_code == 0 and "derived rows updated: 0" in recomputed.output
    reindexed = invoke("reindex")
    assert reindexed.exit_code == 0 and "records indexed:" in reindexed.output
    assert invoke("db", "upgrade").exit_code == 0


def test_check_fails_on_problems(environment: Path) -> None:
    import sqlite3

    assert invoke("db", "upgrade").exit_code == 0
    assert invoke("seed").exit_code == 0
    connection = sqlite3.connect(environment / "app.db")
    try:
        connection.execute("DROP TRIGGER revision_no_update")
        connection.commit()
    finally:
        connection.close()
    result = invoke("check")
    assert result.exit_code == 1
    assert "revision_no_update" in result.output


def test_seed_fails_on_a_broken_codebook(
    environment: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    monkeypatch.setenv("CODEBOOK_DIR", str(broken))
    get_settings.cache_clear()
    missing = invoke("db", "upgrade")
    assert missing.exit_code == 1
    assert "parameters.yaml is missing" in missing.output
    synthetic.write_parameters(broken, synthetic.MINISTRY, synthetic.INVASION)
    (broken / "example.yaml").write_text("vocabulary: example\nterms: {}\n", encoding="utf-8")
    assert invoke("db", "upgrade").exit_code == 0
    result = invoke("seed")
    assert result.exit_code == 1
    assert "terms must be a list" in result.output


def test_serve_flags_take_precedence(environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    assert invoke("db", "upgrade").exit_code == 0
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))
    assert invoke("serve", "--host", "0.0.0.0", "--port", "8080").exit_code == 0
    assert invoke("serve").exit_code == 0
    assert invoke("serve", "--reload").exit_code == 0
    flags, defaults, reload = calls
    assert (flags["app"], flags["factory"], flags["host"], flags["port"]) == (
        "mdt.app:create_app",
        True,
        "0.0.0.0",
        8080,
    )
    assert (defaults["host"], defaults["port"], defaults["reload"]) == ("127.0.0.2", 8181, False)
    assert flags["workers"] == 1 and flags["proxy_headers"] is False
    assert reload["reload"] is True and reload["reload_dirs"]


def test_serve_refuses_to_start_without_a_database(
    environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: pytest.fail("must not start"))
    result = invoke("serve")
    assert result.exit_code == 1
    assert "run `mdt db upgrade`" in result.output
    assert not (environment / "app.db").exists()


def test_health_check_lines_are_dropped_from_the_access_log() -> None:
    health = cli.HealthCheckFilter()

    def record(path: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1", "GET", path, "1.1", 200),
            None,
        )

    assert not health.filter(record("/api/health"))
    assert not health.filter(record("/api/health?probe=1"))
    assert health.filter(record("/api/meta"))
    assert health.filter(logging.LogRecord("x", logging.INFO, "", 0, "plain", None, None))
