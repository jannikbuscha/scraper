"""Raw DDL that SQLAlchemy models cannot express (docs/DATA_MODEL.md §4, §10, §11, §14).

Migrations execute these constants. Any migration that batch-alters ``revision`` or
``raw_snapshot`` must call :func:`create_revision_triggers` or
:func:`create_raw_snapshot_triggers` again, because batch mode recreates the table and
silently drops its triggers.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

REVISION_TRIGGER_NAMES = ("revision_no_update", "revision_no_delete")
RAW_SNAPSHOT_TRIGGER_NAMES = ("raw_snapshot_no_update", "raw_snapshot_no_delete")

RAW_SNAPSHOT_TRIGGERS_DDL = (
    """
    CREATE TRIGGER raw_snapshot_no_update BEFORE UPDATE ON raw_snapshot
    BEGIN
        SELECT RAISE(ABORT, 'raw_snapshot is append-only');
    END
    """,
    """
    CREATE TRIGGER raw_snapshot_no_delete BEFORE DELETE ON raw_snapshot
    BEGIN
        SELECT RAISE(ABORT, 'raw_snapshot is append-only');
    END
    """,
)

REVISION_TRIGGERS_DDL = (
    """
    CREATE TRIGGER revision_no_update BEFORE UPDATE ON revision
    BEGIN
        SELECT RAISE(ABORT, 'revision is append-only');
    END
    """,
    """
    CREATE TRIGGER revision_no_delete BEFORE DELETE ON revision
    BEGIN
        SELECT RAISE(ABORT, 'revision is append-only');
    END
    """,
)

FTS_TABLE_NAMES = ("fts_entity", "fts_document")

_FTS_OPTIONS = "tokenize = \"unicode61 remove_diacritics 2\", prefix = '2 3 4'"

FTS_TABLES_DDL = (
    f"CREATE VIRTUAL TABLE fts_entity USING fts5(body, {_FTS_OPTIONS})",
    f"CREATE VIRTUAL TABLE fts_document USING fts5(title, body, {_FTS_OPTIONS})",
)


def create_revision_triggers(connection: Connection) -> None:
    """(Re)create the append-only triggers on ``revision`` (idempotent)."""
    for name in REVISION_TRIGGER_NAMES:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
    for ddl in REVISION_TRIGGERS_DDL:
        connection.execute(text(ddl))


def create_fts_tables(connection: Connection) -> None:
    """Create both FTS5 tables."""
    for ddl in FTS_TABLES_DDL:
        connection.execute(text(ddl))


def drop_fts_tables(connection: Connection) -> None:
    """Drop both FTS5 tables (their shadow tables go with them)."""
    for name in FTS_TABLE_NAMES:
        connection.execute(text(f"DROP TABLE IF EXISTS {name}"))


def existing_revision_triggers(connection: Connection) -> set[str]:
    """Names of the append-only triggers that exist on ``revision``."""
    rows = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'revision'")
    )
    return {row[0] for row in rows} & set(REVISION_TRIGGER_NAMES)


def create_raw_snapshot_triggers(connection: Connection) -> None:
    """(Re)create the append-only triggers on ``raw_snapshot`` (idempotent)."""
    for name in RAW_SNAPSHOT_TRIGGER_NAMES:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
    for ddl in RAW_SNAPSHOT_TRIGGERS_DDL:
        connection.execute(text(ddl))


def drop_raw_snapshot_triggers(connection: Connection) -> None:
    """Drop the append-only triggers on ``raw_snapshot`` (downgrade of migration 0002)."""
    for name in RAW_SNAPSHOT_TRIGGER_NAMES:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {name}"))


def existing_raw_snapshot_triggers(connection: Connection) -> set[str]:
    """Names of the append-only triggers that exist on ``raw_snapshot``."""
    rows = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'raw_snapshot'")
    )
    return {row[0] for row in rows} & set(RAW_SNAPSHOT_TRIGGER_NAMES)
