"""Application startup: nothing is created implicitly, and a database or codebook that
cannot serve the app stops the start with a clear message."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mdt.app import StartupError, create_app, preflight
from tests.api.conftest import api_settings
from tests.api.helpers import BASE_URL
from tests.conftest import Db


def test_a_missing_database_is_not_created(tmp_path: Path) -> None:
    settings = api_settings(tmp_path)
    with pytest.raises(StartupError, match="mdt db upgrade"):
        create_app(settings)
    assert not (tmp_path / "app.db").exists()


def test_an_unmigrated_database_is_refused(tmp_path: Path) -> None:
    sqlite3.connect(tmp_path / "app.db").close()
    with pytest.raises(StartupError, match="schema is at no revision"):
        preflight(api_settings(tmp_path))


def test_an_outdated_schema_is_refused(api_db: Db, tmp_path: Path) -> None:
    root = tmp_path / "old"
    root.mkdir()
    shutil.copyfile(api_db.root / "app.db", root / "app.db")
    connection = sqlite3.connect(root / "app.db")
    try:
        connection.execute("UPDATE alembic_version SET version_num = 'older'")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StartupError, match="schema is at older"):
        preflight(api_settings(root))


def test_a_missing_codebook_is_refused(api_db: Db, tmp_path: Path) -> None:
    settings = api_settings(api_db.root, codebook_dir=tmp_path / "missing")
    with pytest.raises(StartupError, match="codebook"):
        create_app(settings)


def test_create_app_defaults_to_the_process_settings(
    api_db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("mdt.app.get_settings", lambda: api_db.settings)
    app = create_app()
    engine = app.state.mdt.engine
    disposed: list[bool] = []
    original = engine.dispose

    def dispose() -> None:
        disposed.append(True)
        original()

    monkeypatch.setattr(engine, "dispose", dispose)
    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/api/health").status_code == 200
        assert disposed == []
    assert disposed == [True]  # the lifespan disposes the engine at shutdown
