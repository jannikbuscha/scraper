"""Database layer: migrations, append-only triggers, connection setup, transactions."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, StatementError

from mdt.db import selfcheck
from mdt.db.ddl import create_revision_triggers, existing_revision_triggers
from mdt.db.engine import create_db_engine
from mdt.db.migrate import head_revision, include_name, upgrade_database
from mdt.db.models import Base
from mdt.db.session import (
    create_session_factory,
    read_transaction,
    schema_revision,
    write_transaction,
)
from mdt.db.types import UtcTimestamp
from tests.conftest import Db


def _fresh_database(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgrade_database(url)
    return url


def _insert_revision(connection: sa.Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO revision (entity_type, entity_id, version, at, author, channel, action,"
            " snapshot, diff) VALUES ('project', 'prj_X', 1, '2026-01-01T00:00:00.000000Z',"
            " 'Alice Example', 'ui', 'create', '{}', '{}')"
        )
    )


# --------------------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------------------


def test_upgrade_head_matches_models(tmp_path: Path) -> None:
    engine = create_db_engine(_fresh_database(tmp_path))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"include_name": include_name, "compare_type": True},
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_upgrade_is_idempotent_and_records_head(tmp_path: Path) -> None:
    url = _fresh_database(tmp_path)
    upgrade_database(url)
    connection = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
            (head_revision(),)
        ]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        connection.close()


def test_include_name_skips_fts_and_sqlite_tables() -> None:
    assert not include_name("fts_entity", "table", {})
    assert not include_name("fts_document_data", "table", {})
    assert not include_name("sqlite_sequence", "table", {})
    assert include_name("project", "table", {})
    assert include_name("ix_project_deleted_at", "index", {})


def test_fts_tables_use_the_contract_tokenizer(db: Db) -> None:
    with db.engine.connect() as connection:
        rows: dict[str, str] = dict(
            connection.execute(
                text(
                    "SELECT name, sql FROM sqlite_master"
                    " WHERE name IN ('fts_entity', 'fts_document')"
                )
            ).all()
        )
    assert set(rows) == {"fts_entity", "fts_document"}
    for sql in rows.values():
        assert "fts5" in sql
        assert "unicode61 remove_diacritics 2" in sql
        assert "prefix = '2 3 4'" in sql
    assert "title, body" in rows["fts_document"]


def test_foreign_keys_are_restrict(db: Db) -> None:
    with db.engine.connect() as connection:
        tables = [
            name
            for (name,) in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'fts_%'"
                )
            )
        ]
        keys = [
            (table, row[3], row[6])
            for table in tables
            for row in connection.execute(text(f"PRAGMA foreign_key_list('{table}')"))
        ]
    assert keys, "the schema has foreign keys"
    assert {on_delete for _, _, on_delete in keys} == {"RESTRICT"}
    assert ("service", "project_id", "RESTRICT") in keys


def _indexes(db: Db) -> dict[str, set[tuple[tuple[str, ...], bool]]]:
    result: dict[str, set[tuple[tuple[str, ...], bool]]] = {}
    with db.engine.connect() as connection:
        tables = [
            name
            for (name,) in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'fts_%'"
                )
            )
        ]
        for table in tables:
            for index in connection.execute(text(f"PRAGMA index_list('{table}')")).all():
                columns = tuple(
                    row[2] for row in connection.execute(text(f"PRAGMA index_info('{index[1]}')"))
                )
                result.setdefault(table, set()).add((columns, bool(index[2])))
    return result


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("comment", ("subject_id", "status")),
        ("comment", ("parent_id",)),
        ("service", ("project_id",)),
        ("service", ("parent_service_id",)),
        ("event", ("subject_id",)),
        ("event", ("date_start",)),
        ("participation", ("organization_id",)),
        ("participation", ("subject_id",)),
        ("relation", ("from_id",)),
        ("relation", ("to_id",)),
        ("indicator", ("subject_id",)),
        ("evidence", ("subject_id",)),
        ("document", ("published_start",)),
        ("document", ("retrieved_at",)),
        ("document_link", ("subject_id", "state", "document_id")),
        ("revision", ("at",)),
        ("revision", ("author",)),
        ("revision", ("entity_type", "id")),
        ("revision", ("batch_id",)),
        ("derived", ("period",)),
        ("derived", ("war_trajectory",)),
    ],
)
def test_indexes_of_the_contract_exist(db: Db, table: str, columns: tuple[str, ...]) -> None:
    assert columns in {cols for cols, _ in _indexes(db)[table]}


def test_every_curated_table_indexes_deleted_at(db: Db) -> None:
    indexes = _indexes(db)
    for table in (
        "project",
        "service",
        "event",
        "document",
        "organization",
        "participation",
        "component",
        "relation",
        "indicator",
        "evidence",
        "vocabulary_term",
        "saved_view",
        "comment",
    ):
        assert (("deleted_at",), False) in indexes[table], table


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("project", ("slug",)),
        ("project", ("seed_key",)),
        ("organization", ("slug",)),
        ("organization", ("seed_key",)),
        ("vocabulary_term", ("vocabulary", "code")),
        ("document_link", ("document_id", "subject_id")),
        ("revision", ("entity_id", "version")),
        ("document", ("canonical_url",)),
        ("search_key", ("entity_id",)),
    ],
)
def test_unique_constraints_of_the_contract_exist(
    db: Db, table: str, columns: tuple[str, ...]
) -> None:
    assert (columns, True) in _indexes(db)[table]


# --------------------------------------------------------------------------------------
# Append-only revisions
# --------------------------------------------------------------------------------------


def test_revision_update_and_delete_abort(db: Db) -> None:
    with db.engine.begin() as connection:
        _insert_revision(connection)
    for statement in (
        "UPDATE revision SET note = 'changed' WHERE entity_id = 'prj_X'",
        "DELETE FROM revision WHERE entity_id = 'prj_X'",
    ):
        with pytest.raises(IntegrityError, match="revision is append-only"), db.engine.begin() as c:
            c.execute(text(statement))
    with db.engine.connect() as connection:
        assert connection.execute(text("SELECT note FROM revision WHERE entity_id = 'prj_X'")).all()
    db.check_on_teardown = False  # the raw revision has no entity


def test_both_triggers_exist(db: Db) -> None:
    with db.engine.connect() as connection:
        assert existing_revision_triggers(connection) == {
            "revision_no_update",
            "revision_no_delete",
        }


def test_trigger_helper_recreates_triggers_after_batch_alter(db: Db) -> None:
    with db.engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table("revision", recreate="always") as batch:
            batch.add_column(sa.Column("probe", sa.Text()))
        # Batch mode recreated the table and silently dropped the triggers.
        assert existing_revision_triggers(connection) == set()
        create_revision_triggers(connection)
        create_revision_triggers(connection)  # idempotent
        assert existing_revision_triggers(connection) == {
            "revision_no_update",
            "revision_no_delete",
        }
        _insert_revision(connection)
    with pytest.raises(IntegrityError, match="append-only"), db.engine.begin() as connection:
        connection.execute(text("DELETE FROM revision"))
    db.check_on_teardown = False


# --------------------------------------------------------------------------------------
# Connections and transactions
# --------------------------------------------------------------------------------------


def test_connection_setup_for_file_database(db: Db) -> None:
    with db.engine.connect() as connection:
        driver = connection.connection.driver_connection
        assert isinstance(driver, sqlite3.Connection)
        assert driver.isolation_level is None
        pragma = connection.exec_driver_sql
        assert pragma("PRAGMA foreign_keys").scalar() == 1
        assert pragma("PRAGMA busy_timeout").scalar() == 10000
        assert pragma("PRAGMA synchronous").scalar() == 1  # NORMAL
        assert pragma("PRAGMA journal_mode").scalar() == "wal"
        assert pragma("SELECT mdt_fold('ПРИКЛАД’Х')").scalar() == "прикладʼх"
        assert pragma("SELECT mdt_fold(NULL)").scalar() is None
        assert pragma("SELECT mdt_sortkey('я') > mdt_sortkey('z')").scalar() == 1


def test_in_memory_database_works() -> None:
    engine = create_db_engine("sqlite://")
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "memory"
            assert connection.exec_driver_sql("SELECT mdt_fold('Ab')").scalar() == "ab"
    finally:
        engine.dispose()


def test_json_is_stored_without_ascii_escapes(db: Db) -> None:
    with db.engine.begin() as connection:
        connection.execute(
            sa.insert(Base.metadata.tables["revision"]).values(
                entity_type="project",
                entity_id="prj_X",
                version=1,
                at="2026-01-01T00:00:00.000000Z",
                author="Alice Example",
                channel="ui",
                action="create",
                snapshot={"fields": {"name_uk": "Приклад"}},
                diff={},
            )
        )
    db.check_on_teardown = False  # the raw revision has no entity
    raw = sqlite3.connect(db.root / "app.db")
    try:
        query = "SELECT snapshot FROM revision WHERE entity_id = 'prj_X'"
        assert raw.execute(query).fetchone() == ('{"fields":{"name_uk":"Приклад"}}',)
    finally:
        raw.close()


def test_write_transaction_holds_the_write_lock_before_writing(db: Db, tmp_path: Path) -> None:
    other = sqlite3.connect(db.root / "app.db", timeout=0, isolation_level=None)
    try:
        with db.session() as session:
            with write_transaction(session):
                session.execute(text("SELECT 1"))
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    other.execute("BEGIN IMMEDIATE")
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
            with read_transaction(session):
                session.execute(text("SELECT 1"))
                other.execute("BEGIN IMMEDIATE")  # readers do not block the writer (WAL)
                other.execute("ROLLBACK")
    finally:
        other.close()


def test_write_transaction_rolls_back_on_error(db: Db) -> None:
    with db.session() as session:
        with pytest.raises(RuntimeError), write_transaction(session):
            session.execute(text("INSERT INTO app_state (key, value) VALUES ('probe', 'x')"))
            raise RuntimeError("boom")
        with read_transaction(session):
            assert (
                session.execute(text("SELECT count(*) FROM app_state WHERE key = 'probe'")).scalar()
                == 0
            )


def test_write_units_do_not_nest(db: Db) -> None:
    with db.session() as session:
        with write_transaction(session):
            with pytest.raises(RuntimeError, match="nested"), write_transaction(session):
                pass
            session.execute(text("INSERT INTO app_state (key, value) VALUES ('probe', 'x')"))
        with read_transaction(session):
            assert session.execute(text("SELECT value FROM app_state WHERE key = 'probe'")).scalar()
        with write_transaction(session):  # usable again afterwards
            session.execute(text("DELETE FROM app_state WHERE key = 'probe'"))


def test_write_transaction_refuses_pending_orm_changes(db: Db) -> None:
    from mdt.db.models import AppState

    with db.session() as session:
        session.execute(text("SELECT 1"))
        session.add(AppState(key="pending", value="x"))
        with pytest.raises(RuntimeError, match="pending"), write_transaction(session):
            pass


def test_schema_revision_is_the_alembic_head(db: Db) -> None:
    with db.session() as session:
        assert schema_revision(session) == head_revision()


def test_schema_revision_without_alembic_table() -> None:
    engine = create_db_engine("sqlite://")
    try:
        with create_session_factory(engine)() as session:
            assert schema_revision(session) is None
    finally:
        engine.dispose()


# --------------------------------------------------------------------------------------
# Timestamp type and self-check
# --------------------------------------------------------------------------------------


def test_utc_timestamp_accepts_aware_utc_and_the_storage_format() -> None:
    column = UtcTimestamp()
    dialect = sa.create_engine("sqlite://").dialect
    aware = datetime(2026, 1, 2, 3, 4, 5, 600, tzinfo=UTC)
    assert column.process_bind_param(aware, dialect) == "2026-01-02T03:04:05.000600Z"
    assert column.process_bind_param("2026-01-02T03:04:05.000600Z", dialect) == (
        "2026-01-02T03:04:05.000600Z"
    )
    assert column.process_bind_param(None, dialect) is None


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 1, 2, 3, 4, 5),  # naive
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))),
        "2026-01-02T03:04:05Z",
        "2026-01-02 03:04:05.000000Z",
        "2026-02-30T03:04:05.000000Z",
        "２０２６-01-02T03:04:05.000000Z",
        12,
    ],
)
def test_utc_timestamp_rejects_everything_else(value: object) -> None:
    dialect = sa.create_engine("sqlite://").dialect
    with pytest.raises(ValueError):
        UtcTimestamp().process_bind_param(value, dialect)


def test_bad_timestamp_never_reaches_the_database(db: Db) -> None:
    from mdt.db.models import DocumentText

    with db.session() as session, pytest.raises(StatementError):
        session.add(DocumentText(text_hash="h", text="t", char_count=1, created_at="yesterday"))
        session.flush()


def test_self_check_passes_here() -> None:
    selfcheck.check_sqlite()


def test_self_check_refuses_old_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mdt.db.selfcheck.sqlite3.sqlite_version_info", (3, 39, 4))
    with pytest.raises(selfcheck.SelfCheckError, match="too old"):
        selfcheck.check_sqlite()
