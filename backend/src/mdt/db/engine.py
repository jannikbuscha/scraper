"""Engine factory with the connection setup of docs/DATA_MODEL.md §6.1.

* The DBAPI connection runs with ``isolation_level = None``: the sqlite3 driver never
  begins transactions implicitly. SQLAlchemy's ``begin`` event emits ``BEGIN`` itself,
  or ``BEGIN IMMEDIATE`` when the connection carries the execution option
  :data:`BEGIN_MODE_OPTION` (set by :func:`mdt.db.session.write_transaction`).
* Every connection gets ``foreign_keys=ON``, ``busy_timeout=10000``,
  ``synchronous=NORMAL`` and the SQL functions ``mdt_fold`` and ``mdt_sortkey``.
  File databases are switched to WAL (persistent; ``mdt db upgrade`` sets it as well).
* JSON is serialised with ``ensure_ascii=False``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import ConnectionPoolEntry

from mdt.domain.text import sql_fold, sql_sortkey

#: Execution option naming the BEGIN mode of a connection's next transaction.
BEGIN_MODE_OPTION = "mdt_begin"
_BEGIN_MODES = ("DEFERRED", "IMMEDIATE")
#: How long a connection waits for another writer's lock (e.g. a CLI command running
#: next to the server) before SQLite gives up with SQLITE_BUSY.
BUSY_TIMEOUT_MS = 10_000


def dumps_json(value: Any) -> str:
    """Serialise JSON for storage (UTF-8 text, no ASCII escaping, compact)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_memory_database(url: str) -> bool:
    database = make_url(url).database
    return not database or database == ":memory:" or "mode=memory" in database


def configure_dbapi_connection(dbapi_connection: sqlite3.Connection, *, wal: bool) -> None:
    """Apply the per-connection settings to a raw sqlite3 connection."""
    dbapi_connection.isolation_level = None
    dbapi_connection.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_MS)}")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    if wal:
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.create_function("mdt_fold", 1, sql_fold, deterministic=True)
    dbapi_connection.create_function("mdt_sortkey", 1, sql_sortkey, deterministic=True)


def create_db_engine(url: str, **kwargs: Any) -> Engine:
    """Create an engine for a SQLite URL (file or in-memory) with the MDT setup."""
    wal = not _is_memory_database(url)
    engine = create_engine(url, json_serializer=dumps_json, json_deserializer=json.loads, **kwargs)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
        configure_dbapi_connection(dbapi_connection, wal=wal)

    @event.listens_for(engine, "begin")
    def _on_begin(connection: Connection) -> None:
        mode = connection.get_execution_options().get(BEGIN_MODE_OPTION, "DEFERRED")
        if mode not in _BEGIN_MODES:
            raise ValueError(f"unknown BEGIN mode {mode!r}")
        connection.exec_driver_sql(f"BEGIN {mode}")

    return engine
