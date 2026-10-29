"""The ``mdt`` command-line interface (Typer).

Commands: ``mdt db upgrade``, ``mdt seed [--dry-run]``, ``mdt recompute``, ``mdt check``,
``mdt reindex`` and ``mdt serve [--host] [--port] [--reload]``.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import typer
from sqlalchemy.orm import Session

from mdt.config import BACKEND_DIR, Settings, get_settings
from mdt.db.engine import create_db_engine
from mdt.db.migrate import upgrade_database
from mdt.db.selfcheck import SelfCheckError, check_sqlite
from mdt.db.session import create_session_factory, write_transaction
from mdt.domain import derived, fts
from mdt.domain.check import run_check
from mdt.domain.clock import utc_now
from mdt.domain.seed import SeedFileError, run_seed
from mdt.domain.vocab import CodebookError

app = typer.Typer(help="MDT Portfolio: research data platform.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")

log = logging.getLogger("mdt")


def _setup(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    try:
        check_sqlite()
    except SelfCheckError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    settings.ensure_data_dirs()


@contextmanager
def _session(settings: Settings) -> Iterator[Session]:
    """A session on the configured database; codebook and seed file errors end the
    command with a clear message instead of a traceback."""
    engine = create_db_engine(settings.sqlalchemy_url)
    try:
        with create_session_factory(engine, settings)() as session:
            yield session
    except (CodebookError, SeedFileError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    finally:
        engine.dispose()


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all database migrations, then recompute derived values if their inputs changed."""
    settings = get_settings()
    _setup(settings)
    upgrade_database(settings.sqlalchemy_url)
    with _session(settings) as session, write_transaction(session):
        if derived.ensure_current(session, utc_now(), settings):
            typer.echo("derived values recomputed")
    typer.echo("database is up to date")


@app.command()
def seed(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change; write nothing."
    ),
) -> None:
    """Load vocabularies and seed data (idempotent; never overwrites human edits)."""
    settings = get_settings()
    _setup(settings)
    with _session(settings) as session:
        report = run_seed(session, settings, dry_run=dry_run)
    for line in report.lines():
        typer.echo(line)
    if report.errors:
        raise typer.Exit(1)


@app.command()
def recompute() -> None:
    """Recompute all derived values."""
    settings = get_settings()
    _setup(settings)
    with _session(settings) as session, write_transaction(session):
        written = derived.recompute_all(session, utc_now(), settings)
    typer.echo(f"derived rows updated: {written}")


@app.command()
def check() -> None:
    """Report integrity problems (changes nothing); exits non-zero if any are found."""
    settings = get_settings()
    _setup(settings)
    with _session(settings) as session:
        report = run_check(session, settings)
    for problem in report.problems:
        typer.echo(problem)
    if not report.ok:
        typer.echo(f"{len(report.problems)} problem(s) found", err=True)
        raise typer.Exit(1)
    typer.echo(f"no problems found ({report.entities_checked} records checked)")


@app.command()
def reindex() -> None:
    """Rebuild both full-text search tables (in batches; the app stays usable)."""
    settings = get_settings()
    _setup(settings)
    with _session(settings) as session:
        count = fts.reindex_all(session)
    typer.echo(f"records indexed: {count}")


class HealthCheckFilter(logging.Filter):
    """Drop access-log lines of ``GET /api/health`` (the container health check)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            return str(args[2]).split("?", 1)[0] != "/api/health"
        return True


def _log_config(level: str) -> dict[str, Any]:
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["skip_health"] = {"()": "mdt.cli.HealthCheckFilter"}
    config["handlers"]["access"]["filters"] = ["skip_health"]
    config["loggers"]["mdt"] = {"handlers": ["default"], "level": level, "propagate": False}
    for name in ("uvicorn", "uvicorn.error"):
        config["loggers"].setdefault(name, {})["level"] = level
    return config


@app.command()
def serve(
    host: str | None = typer.Option(None, help="Listen address (default: HOST setting)."),
    port: int | None = typer.Option(None, help="Listen port (default: PORT setting)."),
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes (development)."),
) -> None:
    """Serve the API and the built frontend with uvicorn (one process)."""
    settings = get_settings()
    _setup(settings)
    # The web stack is imported only for this command.
    from mdt.app import StartupError, preflight

    try:
        preflight(settings)
    except StartupError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    import uvicorn

    uvicorn.run(
        "mdt.app:create_app",
        factory=True,
        host=host if host is not None else settings.host,
        port=port if port is not None else settings.port,
        reload=reload,
        reload_dirs=[str(BACKEND_DIR / "src")] if reload else None,
        workers=1,
        log_config=_log_config(settings.log_level),
        # The app needs no client addresses; forwarded headers are never trusted.
        proxy_headers=False,
        server_header=False,
    )
