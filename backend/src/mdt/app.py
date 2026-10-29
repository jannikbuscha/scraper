"""The web application: :func:`create_app` builds it (``mdt serve`` and tests use it).

FastAPI serves the API routes under ``/api`` and the built frontend (``/assets`` and the
SPA fallback); the exception handlers turn every error into the error envelope.

Startup creates nothing: migrations and the seed are CLI steps (``mdt db upgrade``,
``mdt seed``). :func:`preflight` refuses to start with a clear message when SQLite lacks
FTS5, the database is missing or not at the current schema, or
``codebook/parameters.yaml`` is unusable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.telemetry import TelemetryConfig
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from mdt import __version__
from mdt.api import comments, entities, frontend, meta, revisions
from mdt.api.deps import AppContext
from mdt.api.errors import install_error_handlers
from mdt.config import Settings, get_settings
from mdt.db.engine import create_db_engine
from mdt.db.migrate import head_revision
from mdt.db.selfcheck import SelfCheckError, check_sqlite
from mdt.db.session import create_session_factory
from mdt.domain.vocab import CodebookError, load_parameters

#: FastAPI's OpenTelemetry integration stays off: nothing about requests leaves the server.
TELEMETRY_OFF: TelemetryConfig = {
    "auto_configure": False,
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
}


class StartupError(RuntimeError):
    """The application cannot start; the message tells the operator what to do."""


def _check_database(settings: Settings, engine: Engine) -> None:
    url = make_url(settings.sqlalchemy_url)
    database = url.database
    if (
        url.get_backend_name() == "sqlite"
        and database
        and database != ":memory:"
        and not database.startswith("file:")
        and not Path(database).is_file()
    ):
        raise StartupError(
            f"database {database} does not exist; run `mdt db upgrade` and `mdt seed` first"
        )
    try:
        with engine.connect() as connection:
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except OperationalError:
        current = None
    head = head_revision()
    if current != head:
        raise StartupError(
            f"the database schema is at {current or 'no revision'}, this version needs "
            f"{head}; run `mdt db upgrade`"
        )


def preflight(settings: Settings, engine: Engine | None = None) -> None:
    """Check that the application can start; raise :class:`StartupError` otherwise."""
    try:
        check_sqlite()
    except SelfCheckError as exc:
        raise StartupError(str(exc)) from exc
    try:
        load_parameters(settings.codebook_path)
    except CodebookError as exc:
        raise StartupError(f"codebook: {exc}") from exc
    own_engine = engine is None
    checked = create_db_engine(settings.sqlalchemy_url) if engine is None else engine
    try:
        _check_database(settings, checked)
    finally:
        if own_engine:
            checked.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application for ``settings`` (default: the process settings)."""
    settings = settings or get_settings()
    engine = create_db_engine(settings.sqlalchemy_url)
    try:
        preflight(settings, engine)
    except BaseException:
        engine.dispose()
        raise

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="MDT Portfolio API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
        lifespan=lifespan,
        telemetry=TELEMETRY_OFF,
    )
    app.state.mdt = AppContext(settings, engine, create_session_factory(engine, settings))
    install_error_handlers(app)
    for routes in (meta, entities, comments, revisions):
        routes.register(app)
    frontend.install(app, settings.frontend_dist_path)
    return app
