"""Running Alembic migrations from code (``mdt db upgrade``, tests).

``alembic.ini`` and ``migrations/`` are located relative to this package, so the
commands work from any working directory. ``migrations/env.py`` connects through
:func:`mdt.db.engine.create_db_engine`, which also switches file databases to WAL.
"""

from __future__ import annotations

from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from mdt.config import BACKEND_DIR

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
