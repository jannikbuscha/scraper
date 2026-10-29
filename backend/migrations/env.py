"""Alembic environment for MDT Portfolio (docs/DATA_MODEL.md §11).

* Batch mode (``render_as_batch=True``), required for ALTER TABLE on SQLite.
* The FTS5 tables (``fts_*`` and their shadow tables) and ``sqlite_*`` objects are
  excluded from autogenerate comparisons; their DDL lives in :mod:`mdt.db.ddl`.
* Foreign keys are switched off while migrating (batch mode recreates tables) and
  ``PRAGMA foreign_key_check`` must report no rows afterwards.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from mdt.config import get_settings
from mdt.db.engine import create_db_engine
from mdt.db.migrate import include_name
from mdt.db.models import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url") or config.get_main_option("sqlalchemy.url")
    if url:
        return str(url)
    settings = get_settings()
    settings.ensure_data_dirs()
    return settings.sqlalchemy_url


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_name,
        compare_type=True,
        # SQLite supports transactional DDL: all migrations run as one transaction.
        transactional_ddl=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against the database."""
    engine = create_db_engine(_database_url())
    try:
        with engine.connect() as connection:
            driver_connection = connection.connection.driver_connection
            assert driver_connection is not None
            # Outside any transaction, otherwise SQLite ignores the pragma.
            driver_connection.execute("PRAGMA foreign_keys=OFF")
            _configure(connection)
            with context.begin_transaction():
                context.run_migrations()
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.rollback()
            driver_connection.execute("PRAGMA foreign_keys=ON")
            if violations:
                raise RuntimeError(f"foreign key violations after migration: {violations[:10]}")
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
