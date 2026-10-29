"""Fixtures of the HTTP API tests.

The database is built with the REAL codebook and seed files of the repository
(``alembic upgrade head`` + ``mdt seed``, once per test session); every test gets a fresh
copy, and ``mdt check`` must be clean afterwards. Records that tests create carry
obviously synthetic values ("Example …", example.org).

``client`` is a TestClient that behaves like the UI's fetch wrapper: it sends
``X-Requested-With: mdt`` on every request and ``X-Author`` plus JSON on writes.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mdt.app import create_app
from mdt.config import REPO_ROOT, Settings
from mdt.db.migrate import upgrade_database
from mdt.domain.check import run_check
from mdt.domain.seed import run_seed
from tests.api.helpers import BASE_URL, ApiClient
from tests.conftest import Db, make_settings, open_db

REAL_CODEBOOK = REPO_ROOT / "codebook"
REAL_SEED = REPO_ROOT / "seed"
FOCAL_ORG_SEED_KEY = "ministry-of-digital-transformation"


def api_settings(root: Path, **overrides: Any) -> Settings:
    """Settings for a database in ``root`` with the real codebook and seed; by default
    there is no frontend build."""
    values: dict[str, Any] = {
        "focal_org_seed_key": FOCAL_ORG_SEED_KEY,
        "allowed_hosts": "127.0.0.1,localhost",
        "frontend_dist": root / "no-frontend-build",
        "team_members": "Alice Example,Bob Example",
        **overrides,
    }
    return make_settings(root, REAL_CODEBOOK, REAL_SEED, **values)


@pytest.fixture(scope="session")
def real_template_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A migrated database seeded from the real codebook and seed files."""
    root = tmp_path_factory.mktemp("api-template")
    settings = api_settings(root)
    upgrade_database(settings.sqlalchemy_url)
    database = open_db(root, settings)
    try:
        with database.session() as session:
            report = run_seed(session, settings)
            assert not report.errors, report.errors
            check = run_check(session, settings)
        assert check.ok, check.problems
    finally:
        database.engine.dispose()
    connection = sqlite3.connect(root / "app.db")
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return root / "app.db"


def _written(root: Path, before: os.stat_result) -> bool:
    """True if anything was written to the copied database: WAL frames were appended or
    the main file changed (a checkpoint)."""
    wal = root / "app.db-wal"
    after = (root / "app.db").stat()
    changed = (after.st_mtime_ns, after.st_size) != (before.st_mtime_ns, before.st_size)
    return changed or (wal.exists() and wal.stat().st_size > 0)


@pytest.fixture
def api_db(tmp_path: Path, real_template_db: Path) -> Iterator[Db]:
    """A fresh copy of the real-seed database. If the test wrote anything, ``mdt check``
    must be clean afterwards (the unchanged template is checked once per session)."""
    root = tmp_path / "data"
    root.mkdir()
    shutil.copyfile(real_template_db, root / "app.db")
    before = (root / "app.db").stat()
    database = open_db(root, api_settings(root))
    try:
        yield database
        if database.check_on_teardown and _written(root, before):
            with database.session() as session:
                report = run_check(session, database.settings)
            assert report.ok, report.problems
    finally:
        database.engine.dispose()


@pytest.fixture
def app(api_db: Db) -> FastAPI:
    """The application on the test database."""
    return create_app(api_db.settings)


@pytest.fixture
def raw_client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient without default headers (for the request-guard tests)."""
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def client(app: FastAPI) -> Iterator[ApiClient]:
    """A client that sends the headers of the UI's fetch wrapper."""
    with TestClient(app, base_url=BASE_URL, headers={"X-Requested-With": "mdt"}) as test_client:
        yield ApiClient(test_client)
