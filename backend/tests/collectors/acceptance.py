"""The environment of the collector acceptance tests (docs/COLLECTORS.md §12.1).

* ``acceptance_template``: one database per test session built like a fresh server: the
  migrations (``alembic upgrade head``) and the seed with the REAL codebook and seed files
  of the repository (``mdt seed``), so the seed projects and vocabularies are those a
  collector meets on a real server.
* ``acceptance``: a fresh copy per test (``mdt check`` must be clean afterwards) with
  helpers to run a real collector through the run framework with the replay transport
  (fixtures, never the network) and to read back everything a run may write.

Import the two fixtures into a test module to use them.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mdt.app import create_app
from mdt.collectors.replay import ReplayTransport
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.throttle import HostThrottle
from mdt.config import Settings
from mdt.db.migrate import upgrade_database
from mdt.db.models import (
    CollectorRun,
    DocumentLink,
    DocumentText,
    Proposal,
    Revision,
    SourceObservation,
)
from mdt.db.session import read_transaction
from mdt.domain.check import run_check
from mdt.domain.records import table_of
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.seed import run_seed
from tests.api.conftest import api_settings
from tests.api.helpers import BASE_URL
from tests.collectors.conftest import FIXTURES, TEST_EMAIL, FakeClock
from tests.conftest import Db, open_db

#: The curated types whose rows a run may create (every curated type is counted).
CURATED_TYPES = tuple(name for name, spec in ENTITY_TYPES.items() if spec.curated)


def acceptance_settings(root: Path, **overrides: Any) -> Settings:
    """Settings for a database in ``root`` with the real codebook, seed and
    ``sources.yaml``; ``CONTACT_EMAIL`` reaches nobody (replay runs do not need it)."""
    return api_settings(root, contact_email=TEST_EMAIL, **overrides)


@pytest.fixture(scope="session")
def acceptance_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A migrated database seeded from the real codebook and seed files."""
    root = tmp_path_factory.mktemp("acceptance-template")
    settings = acceptance_settings(root)
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


@dataclass(frozen=True)
class State:
    """Everything a collector run may write to curated data and proposals."""

    records: Mapping[str, int]  # curated type → rows (deleted ones included)
    revisions: int
    proposals: Mapping[str, str]  # proposal ID → state
    texts: int
    links: Mapping[str, tuple[tuple[str, str, str], ...]]  # document → (subject, origin, state)


@dataclass
class Acceptance:
    """One fresh database with the real seed, and collector runs against fixtures."""

    db: Db

    @property
    def settings(self) -> Settings:
        """The settings of the test database."""
        return self.db.settings

    def run(
        self,
        collector: str,
        fixtures: str | Sequence[str],
        *,
        mode: str = "incremental",
        params: Mapping[str, Any] | None = None,
    ) -> str:
        """Start and execute one run of ``collector`` whose requests are answered by the
        fixture directories ``fixtures`` (names under ``backend/tests/fixtures``)."""
        names = [fixtures] if isinstance(fixtures, str) else list(fixtures)
        transport = ReplayTransport([FIXTURES / name for name in names])
        request = RunRequest(collector, mode=mode, params=dict(params or {}), trigger="cli")
        with self.db.session() as session:
            run_id = start_run(session, self.settings, request, transport=transport)
        environment = RunEnvironment(
            transport=transport, clock=FakeClock(), throttle=HostThrottle()
        )
        execute_run(self.db.factory, self.settings, run_id, environment=environment)
        return run_id

    def state(self) -> State:
        """The current :class:`State`."""
        with self.db.session() as session, read_transaction(session):
            records = {
                name: int(
                    session.scalar(select(func.count()).select_from(table_of(ENTITY_TYPES[name])))
                    or 0
                )
                for name in CURATED_TYPES
            }
            links: dict[str, list[tuple[str, str, str]]] = {}
            for row in session.execute(
                select(
                    DocumentLink.document_id,
                    DocumentLink.subject_id,
                    DocumentLink.origin,
                    DocumentLink.state,
                ).order_by(DocumentLink.document_id, DocumentLink.subject_id)
            ):
                links.setdefault(row.document_id, []).append(
                    (row.subject_id, row.origin, row.state)
                )
            return State(
                records=records,
                revisions=int(session.scalar(select(func.count()).select_from(Revision)) or 0),
                proposals={
                    str(row.id): str(row.state)
                    for row in session.execute(select(Proposal.id, Proposal.state))
                },
                texts=int(session.scalar(select(func.count()).select_from(DocumentText)) or 0),
                links={document: tuple(items) for document, items in links.items()},
            )

    def run_row(self, run_id: str) -> dict[str, Any]:
        """The ``collector_run`` row of ``run_id`` as a dict."""
        with self.db.session() as session, read_transaction(session):
            row = session.get(CollectorRun, run_id)
            assert row is not None
            return {
                "status": row.status,
                "complete_listing": bool(row.complete_listing),
                "stats": dict(row.stats),
                "error": row.error,
            }

    def observations(self, collector: str) -> dict[str, dict[str, Any]]:
        """The observations of ``collector`` by key."""
        with self.db.session() as session, read_transaction(session):
            rows = session.scalars(
                select(SourceObservation).where(SourceObservation.collector == collector)
            ).all()
            return {
                row.key: {
                    "subject_id": row.subject_id,
                    "external_id": row.external_id,
                    "url": row.url,
                    "label": row.label,
                    "last_seen_run": row.last_seen_run,
                    "present": bool(row.present),
                    "details": dict(row.details or {}),
                }
                for row in rows
            }

    def proposals(self, **conditions: Any) -> list[dict[str, Any]]:
        """Proposal rows (as dicts) matching column ``conditions``, oldest first."""
        table = Proposal.__table__
        with self.db.session() as session, read_transaction(session):
            statement = select(table).order_by(table.c.created_at, table.c.id)
            for name, value in conditions.items():
                statement = statement.where(table.c[name] == value)
            return [dict(row) for row in session.execute(statement).mappings()]

    @contextmanager
    def api(self) -> Iterator[TestClient]:
        """A TestClient of the app on the test database."""
        with TestClient(create_app(self.settings), base_url=BASE_URL) as client:
            yield client


@pytest.fixture
def acceptance(tmp_path: Path, acceptance_template: Path) -> Iterator[Acceptance]:
    """A fresh copy of the real-seed database; ``mdt check`` must be clean afterwards."""
    root = tmp_path / "data"
    root.mkdir()
    shutil.copyfile(acceptance_template, root / "app.db")
    database = open_db(root, acceptance_settings(root))
    try:
        yield Acceptance(database)
        if database.check_on_teardown:
            with database.session() as session:
                report = run_check(session, database.settings)
            assert report.ok, report.problems
    finally:
        database.engine.dispose()
