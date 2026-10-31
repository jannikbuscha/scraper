"""Migration 0002 (docs/DATA_MODEL.md §11 item 7, §14): upgrade of a database with Phase 1
data, downgrade, the append-only triggers on ``raw_snapshot`` and the partial unique
indexes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mdt.db.ddl import RAW_SNAPSHOT_TRIGGER_NAMES, existing_raw_snapshot_triggers
from mdt.db.engine import create_db_engine
from mdt.db.migrate import alembic_config, head_revision
from mdt.domain.check import run_check
from mdt.domain.seed import run_seed
from tests.conftest import Db, make_settings, open_db

PHASE2_TABLES = {
    "collector_run",
    "raw_snapshot",
    "fetch_log",
    "run_message",
    "source_observation",
    "proposal",
    "merge_log",
    "import_run",
}
TS = "2026-10-30T10:00:00.000000Z"


def _tables(url: str) -> set[str]:
    engine = create_db_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(url: str, table: str) -> list[str]:
    engine = create_db_engine(url)
    try:
        return [column["name"] for column in sa.inspect(engine).get_columns(table)]
    finally:
        engine.dispose()


def _phase1_database(root: Path, codebook: Path, seed: Path) -> Db:
    """A database at revision 0001 with seeded Phase 1 data."""
    settings = make_settings(root, codebook, seed)
    command.upgrade(alembic_config(settings.sqlalchemy_url), "0001")
    database = open_db(root, settings)
    with database.session() as session:
        report = run_seed(session, settings)
    assert not report.errors
    return database


def test_head_is_0002_and_follows_0001() -> None:
    assert head_revision() == "0002"


def test_upgrade_of_a_phase1_database_keeps_its_data(
    tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> None:
    database = _phase1_database(tmp_path, codebook_dir, seed_dir)
    url = database.settings.sqlalchemy_url
    try:
        with database.engine.connect() as connection:
            before = connection.execute(
                text("SELECT id, version, field_meta FROM organization ORDER BY id")
            ).all()
            revisions = connection.execute(text("SELECT count(*) FROM revision")).scalar_one()
        assert not PHASE2_TABLES & _tables(url)
        command.upgrade(alembic_config(url), "head")
        assert _tables(url) >= PHASE2_TABLES
        with database.engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0002"
            )
            after = connection.execute(
                text("SELECT id, version, field_meta FROM organization ORDER BY id")
            ).all()
            assert after == before
            assert connection.execute(text("SELECT count(*) FROM revision")).scalar_one() == (
                revisions
            )
        with database.session() as session:
            report = run_check(session, database.settings)
        assert report.ok, report.problems
    finally:
        database.engine.dispose()


def test_upgrade_adds_source_record_at_without_rebuilding_document(
    tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> None:
    database = _phase1_database(tmp_path, codebook_dir, seed_dir)
    url = database.settings.sqlalchemy_url
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document (id, version, created_at, created_by, updated_at,"
                    " updated_by, title, url, canonical_url, archive_urls, field_meta)"
                    " VALUES ('doc_01JBX3EXAMPLE0000000000000', 1, :ts, 'user', :ts, 'user',"
                    " 'Example document', 'https://example.org/a', 'https://example.org/a',"
                    " '[]', '{}')"
                ),
                {"ts": TS},
            )
            index_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'uq_document_canonical_url_live'")
            ).scalar_one()
        command.upgrade(alembic_config(url), "head")
        columns = _columns(url, "document")
        assert columns[-1] == "source_record_at"  # appended by ALTER TABLE, not rebuilt
        with database.engine.connect() as connection:
            row = connection.execute(
                text("SELECT title, canonical_url, source_record_at FROM document")
            ).one()
            assert tuple(row) == ("Example document", "https://example.org/a", None)
            assert (
                connection.execute(
                    text(
                        "SELECT sql FROM sqlite_master"
                        " WHERE name = 'uq_document_canonical_url_live'"
                    )
                ).scalar_one()
                == index_sql
            )
            indexes = {
                name
                for (name,) in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE tbl_name = 'document'")
                )
            }
            assert "ix_document_source_id_external_id" in indexes
    finally:
        database.engine.dispose()


def test_downgrade_drops_what_the_upgrade_created(
    tmp_path: Path, codebook_dir: Path, seed_dir: Path
) -> None:
    database = _phase1_database(tmp_path, codebook_dir, seed_dir)
    url = database.settings.sqlalchemy_url
    database.engine.dispose()
    phase1_tables = _tables(url)
    phase1_columns = _columns(url, "document")
    command.upgrade(alembic_config(url), "head")
    command.downgrade(alembic_config(url), "0001")
    assert _tables(url) == phase1_tables
    assert _columns(url, "document") == phase1_columns
    connection = sqlite3.connect(tmp_path / "app.db")
    try:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        assert not set(RAW_SNAPSHOT_TRIGGER_NAMES) & names
        assert "ix_document_source_id_external_id" not in names
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0001",)
    finally:
        connection.close()
    command.upgrade(alembic_config(url), "head")  # and up again
    assert _tables(url) >= PHASE2_TABLES


def _insert_run(connection: sa.Connection, run_id: str, status: str) -> None:
    connection.execute(
        text(
            "INSERT INTO collector_run (id, collector, trigger, mode, status, started_at,"
            " code_version, config_hash) VALUES (:id, 'example', 'cli', 'incremental', :status,"
            " :ts, '0.0.0', 'hash')"
        ),
        {"id": run_id, "status": status, "ts": TS},
    )


def _insert_snapshot(connection: sa.Connection, raw_id: str) -> None:
    connection.execute(
        text(
            "INSERT INTO raw_snapshot (id, source_id, via, fetched_at, sha256, size)"
            " VALUES (:id, 'manual', 'upload', :ts, 'abc', 3)"
        ),
        {"id": raw_id, "ts": TS},
    )


def test_raw_snapshot_rows_are_append_only(db: Db) -> None:
    with db.engine.begin() as connection:
        _insert_snapshot(connection, "raw_01")
        assert existing_raw_snapshot_triggers(connection) == set(RAW_SNAPSHOT_TRIGGER_NAMES)
    for statement in (
        "UPDATE raw_snapshot SET size = 4 WHERE id = 'raw_01'",
        "DELETE FROM raw_snapshot WHERE id = 'raw_01'",
    ):
        with (
            pytest.raises(sa.exc.DatabaseError, match="raw_snapshot is append-only"),
            db.engine.begin() as connection,
        ):
            connection.execute(text(statement))


def test_at_most_one_running_run(db: Db) -> None:
    with db.engine.begin() as connection:
        _insert_run(connection, "run_a", "running")
        _insert_run(connection, "run_b", "succeeded")
        _insert_run(connection, "run_c", "failed")
    with pytest.raises(IntegrityError), db.engine.begin() as connection:
        _insert_run(connection, "run_d", "running")


def test_at_most_one_open_proposal_per_dedup_key(db: Db) -> None:
    def insert(connection: sa.Connection, proposal_id: str, state: str) -> None:
        connection.execute(
            text(
                "INSERT INTO proposal (id, kind, state, entity_type, collector, first_run_id,"
                " last_run_id, dedup_key, created_at, last_seen_at) VALUES (:id,"
                " 'update_field', :state, 'project', 'example', 'run_a', 'run_a', 'key', :ts,"
                " :ts)"
            ),
            {"id": proposal_id, "state": state, "ts": TS},
        )

    with db.engine.begin() as connection:
        _insert_run(connection, "run_a", "succeeded")
        insert(connection, "prp_a", "open")
        insert(connection, "prp_b", "rejected")
        insert(connection, "prp_c", "superseded")
    with pytest.raises(IntegrityError), db.engine.begin() as connection:
        insert(connection, "prp_d", "open")


def test_foreign_keys_restrict(db: Db) -> None:
    with pytest.raises(IntegrityError), db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fetch_log (run_id, at, method, url, host, purpose, outcome)"
                " VALUES ('run_missing', :ts, 'GET', 'https://example.org/', 'example.org',"
                " 'content', 'ok')"
            ),
            {"ts": TS},
        )
