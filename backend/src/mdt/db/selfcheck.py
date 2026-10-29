"""Startup self-check (docs/DATA_MODEL.md §11.6): SQLite ≥ 3.40 with FTS5."""

from __future__ import annotations

import sqlite3

MIN_SQLITE_VERSION = (3, 40, 0)


class SelfCheckError(RuntimeError):
    """The runtime cannot run MDT Portfolio; the message says why."""


def check_sqlite() -> None:
    """Raise :class:`SelfCheckError` unless SQLite is recent enough and has FTS5."""
    version = sqlite3.sqlite_version_info
    if version < MIN_SQLITE_VERSION:
        required = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise SelfCheckError(
            f"SQLite {sqlite3.sqlite_version} is too old; MDT Portfolio needs {required} or newer."
        )
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.mdt_fts_probe USING fts5(body)")
    except sqlite3.OperationalError as exc:
        raise SelfCheckError(
            "SQLite was built without FTS5; MDT Portfolio needs FTS5 for full-text search."
        ) from exc
    finally:
        connection.close()
