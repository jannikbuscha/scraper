"""Session factory and transaction helpers (docs/DATA_MODEL.md §6.1)."""

from __future__ import annotations

import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from mdt.config import Settings, get_settings
from mdt.db.engine import BEGIN_MODE_OPTION

SETTINGS_KEY = "mdt.settings"
_WRITE_UNIT_KEY = "mdt.write_unit"
_schema_revisions: weakref.WeakKeyDictionary[Engine, str | None] = weakref.WeakKeyDictionary()


def create_session_factory(
    engine: Engine, settings: Settings | None = None
) -> sessionmaker[Session]:
    """Return a session factory; the settings travel with every session (``session.info``)."""
    info: dict[str, Any] = {SETTINGS_KEY: settings} if settings is not None else {}
    return sessionmaker(bind=engine, info=info, expire_on_commit=True)


def session_settings(session: Session) -> Settings:
    """The settings attached to ``session`` (falls back to the process settings)."""
    settings = session.info.get(SETTINGS_KEY)
    return settings if isinstance(settings, Settings) else get_settings()


@contextmanager
def write_transaction(session: Session) -> Iterator[Session]:
    """Run one write unit: ``BEGIN IMMEDIATE`` … ``COMMIT`` (``ROLLBACK`` on error).

    A read transaction the caller left open is ended first (it must not hold pending
    ORM changes). Everything inside the block, including the first read of the row,
    runs while holding the database write lock. Write units do not nest: committing an
    enclosing unit early would break its all-or-nothing guarantee.
    """
    if session.info.get(_WRITE_UNIT_KEY):
        raise RuntimeError("write units cannot be nested")
    if session.in_transaction():
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("write_transaction() needs a session without pending changes")
        session.commit()
    session.connection(execution_options={BEGIN_MODE_OPTION: "IMMEDIATE"})
    session.info[_WRITE_UNIT_KEY] = True
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    else:
        session.commit()
    finally:
        session.info.pop(_WRITE_UNIT_KEY, None)


@contextmanager
def read_transaction(session: Session) -> Iterator[Session]:
    """Run a read-only unit (plain ``BEGIN``); it is rolled back at the end."""
    if session.in_transaction():
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("read_transaction() needs a session without pending changes")
        session.commit()
    try:
        yield session
    finally:
        session.rollback()


def schema_revision(session: Session) -> str | None:
    """The Alembic revision of the database (read once per engine)."""
    engine = session.get_bind().engine
    if engine not in _schema_revisions:
        try:
            value = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        except OperationalError:
            value = None
        _schema_revisions[engine] = value
    return _schema_revisions[engine]
