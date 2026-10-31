"""Shared fixtures.

* ``no_network`` (autouse): every test stays offline (docs/COLLECTORS.md §12). A real
  ``httpx2`` transport refuses every host but the loopback interface, which the threaded
  local-server tests of the polite client use.
* ``template_db``: one migrated database per test session (``alembic upgrade head``,
  never ``create_all``), seeded with the synthetic codebook and focal organisation.
* ``db``: a fresh copy of the template per test. After the test, ``mdt check`` must find
  nothing, so every test also proves that rows, revisions, FTS and derived rows agree.
  Tests that corrupt the database on purpose set ``db.check_on_teardown = False``.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from mdt.config import Settings
from mdt.db.engine import create_db_engine
from mdt.db.migrate import upgrade_database
from mdt.db.session import create_session_factory
from mdt.domain.check import run_check
from mdt.domain.seed import run_seed
from tests import synthetic

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real transport refuses every host but the loopback interface."""
    original = httpx2.HTTPTransport.handle_request

    def guarded(self: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        if request.url.host not in _LOOPBACK:
            raise AssertionError(f"tests must not reach the network: {request.url}")
        return original(self, request)

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", guarded)


def make_settings(root: Path, codebook: Path, seed: Path, **overrides: Any) -> Settings:
    """Settings for a database in ``root`` (no ``.env`` file is read)."""
    values: dict[str, Any] = {
        "data_dir": root,
        "database_url": f"sqlite:///{root / 'app.db'}",
        "codebook_dir": codebook,
        "seed_dir": seed,
        "focal_org_seed_key": synthetic.FOCAL_ORG_SEED_KEY,
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class Db:
    """A test database: engine, session factory and settings."""

    engine: Engine
    factory: sessionmaker[Session]
    settings: Settings
    root: Path
    check_on_teardown: bool = True

    def session(self) -> Session:
        """A new session (the caller closes it)."""
        return self.factory()


def open_db(root: Path, settings: Settings) -> Db:
    """Open the database in ``root`` with ``settings``."""
    engine = create_db_engine(settings.sqlalchemy_url)
    return Db(engine, create_session_factory(engine, settings), settings, root)


@pytest.fixture(scope="session")
def codebook_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic codebook (shared; tests must not modify it)."""
    return synthetic.write_codebook(tmp_path_factory.mktemp("codebook"))


@pytest.fixture(scope="session")
def seed_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic seed (focal organisation only; shared)."""
    return synthetic.write_seed(tmp_path_factory.mktemp("seed"))


@pytest.fixture(scope="session")
def template_db(
    tmp_path_factory: pytest.TempPathFactory, codebook_dir: Path, seed_dir: Path
) -> Path:
    """A migrated and seeded database file that tests copy."""
    root = tmp_path_factory.mktemp("template")
    settings = make_settings(root, codebook_dir, seed_dir)
    upgrade_database(settings.sqlalchemy_url)
    database = open_db(root, settings)
    try:
        with database.session() as session:
            report = run_seed(session, settings)
        assert not report.errors, report.errors
    finally:
        database.engine.dispose()
    connection = sqlite3.connect(root / "app.db")
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return root / "app.db"


@pytest.fixture
def db(tmp_path: Path, template_db: Path, codebook_dir: Path, seed_dir: Path) -> Iterator[Db]:
    """A fresh database for one test; ``mdt check`` must be clean afterwards."""
    root = tmp_path / "data"
    root.mkdir()
    shutil.copyfile(template_db, root / "app.db")
    database = open_db(root, make_settings(root, codebook_dir, seed_dir))
    try:
        yield database
        if database.check_on_teardown:
            with database.session() as session:
                report = run_check(session, database.settings)
            assert report.ok, report.problems
    finally:
        database.engine.dispose()


@pytest.fixture
def session(db: Db) -> Iterator[Session]:
    """A session on the test database."""
    with db.session() as current:
        yield current
