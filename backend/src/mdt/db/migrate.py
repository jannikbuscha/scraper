"""Running Alembic migrations from code (``mdt db upgrade``, tests).

``alembic.ini`` and ``migrations/`` are located relative to this package, so the
commands work from any working directory. ``migrations/env.py`` connects through
:func:`mdt.db.engine.create_db_engine`, which also switches file databases to WAL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from mdt.config import BACKEND_DIR
from mdt.db.engine import create_db_engine

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    """Autogenerate filter: skip the FTS5 tables (``fts_*``, including their shadow
    tables) and SQLite's internal tables (``sqlite_*``), DATA_MODEL §11.2."""
    if type_ == "table" and name is not None:
        return not name.startswith(("fts_", "sqlite_"))
    return True


def alembic_config(database_url: str) -> Config:
    """Alembic configuration for ``database_url`` (passed via ``attributes``, so URLs
    containing ``%`` need no escaping)."""
    config = Config(str(ALEMBIC_INI)) if ALEMBIC_INI.is_file() else Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = database_url
    return config


def head_revision() -> str:
    """The head revision of the migration scripts."""
    head = ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()
    if head is None:
        raise RuntimeError(f"no migrations found in {MIGRATIONS_DIR}")
    return head


def upgrade_database(database_url: str) -> None:
    """Apply all migrations (``alembic upgrade head``)."""
    command.upgrade(alembic_config(database_url), "head")


def database_problem(database_url: str, engine: Engine | None = None) -> str | None:
    """Why the database cannot serve the app or a command that reads or writes data, or
    None: the SQLite file does not exist (it is not opened, so nothing is created), or its
    schema is not at the head revision. The message names the command to run."""
    url = make_url(database_url)
    database = url.database
    if (
        url.get_backend_name() == "sqlite"
        and database
        and database != ":memory:"
        and not database.startswith("file:")
        and not Path(database).is_file()
    ):
        return f"database {database} does not exist; run `mdt db upgrade` and `mdt seed` first"
    checked = create_db_engine(database_url) if engine is None else engine
    try:
        with checked.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except OperationalError:
        current = None
    finally:
        if engine is None:
            checked.dispose()
    head = head_revision()
    if current is None:
        return (
            f"the database schema is at no revision, this version needs {head}; "
            "run `mdt db upgrade` and `mdt seed`"
        )
    if current != head:
        return (
            f"the database schema is at {current}, this version needs {head}; run `mdt db upgrade`"
        )
    return None
