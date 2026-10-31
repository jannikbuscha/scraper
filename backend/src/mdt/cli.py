"""The ``mdt`` command-line interface (Typer).

Commands: ``mdt db upgrade``, ``mdt seed [--dry-run]``, ``mdt recompute``,
``mdt check [--deep]``, ``mdt reindex``, ``mdt serve [--host] [--port] [--reload]`` and, for
data acquisition (docs/COLLECTORS.md §11), ``mdt collect``, ``mdt runs [show]``,
``mdt fixtures capture`` and ``mdt sources check``; ``mdt import`` for tabular imports
(§9).
"""

from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx2
import typer
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer._click.exceptions import UsageError  # the Click copy Typer runs on
from typer.core import TyperCommand

from mdt.collectors.errors import CollectorUnavailableError, RunInProgressError
from mdt.collectors.fixtures import capture_fixtures, default_out_dir
from mdt.collectors.runs import (
    RunEnvironment,
    RunRequest,
    check_runs,
    execute_run,
    list_runs,
    request_cancel,
    run_detail,
    sources_of,
    start_run,
)
from mdt.collectors.sourcecheck import HostCheck, check_collector, check_urls
from mdt.collectors.sources import SourcesConfig, SourcesError
from mdt.collectors.store import SnapshotStore
from mdt.config import BACKEND_DIR, Settings, contact_email_problem, get_settings
from mdt.db.ddl import RAW_SNAPSHOT_TRIGGER_NAMES, existing_raw_snapshot_triggers
from mdt.db.engine import create_db_engine
from mdt.db.migrate import database_problem, upgrade_database
from mdt.db.models import Project, RunMessage
from mdt.db.selfcheck import SelfCheckError, check_sqlite
from mdt.db.session import create_session_factory, read_transaction, write_transaction
from mdt.domain import derived, fts
from mdt.domain.check import run_check
from mdt.domain.clock import utc_now
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.seed import SeedFileError, run_seed
from mdt.domain.vocab import CodebookError
from mdt.importers.tabular import (
    MAX_PLAN_ROWS,
    ImportRequest,
    Plan,
    dry_run_import,
    preview_import,
    run_import,
)

app = typer.Typer(help="MDT Portfolio: research data platform.", no_args_is_help=True)
db_app = typer.Typer(help="Database commands.", no_args_is_help=True)
app.add_typer(db_app, name="db")
runs_app = typer.Typer(help="Collector runs (list, or `show` one).", invoke_without_command=True)
app.add_typer(runs_app, name="runs")
fixtures_app = typer.Typer(help="Test fixtures from the sources.", no_args_is_help=True)
app.add_typer(fixtures_app, name="fixtures")
sources_app = typer.Typer(help="Source checks.", no_args_is_help=True)
app.add_typer(sources_app, name="sources")

log = logging.getLogger("mdt")


def _setup(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    try:
        check_sqlite()
    except SelfCheckError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    settings.ensure_data_dirs()


def _require_database(settings: Settings) -> None:
    """Commands that read or write data need the database at the current schema; otherwise
    an ``error:`` line and exit 1 before anything opens the database file (which would
    create an empty one), as ``mdt serve`` does."""
    problem = database_problem(settings.sqlalchemy_url)
    if problem is not None:
        typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1)


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
    _require_database(settings)
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
    _require_database(settings)
    with _session(settings) as session, write_transaction(session):
        written = derived.recompute_all(session, utc_now(), settings)
    typer.echo(f"derived rows updated: {written}")


@app.command()
def check(
    deep: bool = typer.Option(
        False, "--deep", help="Also re-hash every raw snapshot file and compare its SHA-256."
    ),
) -> None:
    """Report integrity problems (changes nothing); exits non-zero if any are found."""
    settings = get_settings()
    _setup(settings)
    _require_database(settings)
    with _session(settings) as session:
        report = run_check(session, settings)
        problems = report.problems + _acquisition_problems(session, settings, deep=deep)
    for problem in problems:
        typer.echo(problem)
    if problems:
        typer.echo(f"{len(problems)} problem(s) found", err=True)
        raise typer.Exit(1)
    typer.echo(f"no problems found ({report.entities_checked} records checked)")


def _acquisition_problems(session: Session, settings: Settings, *, deep: bool) -> list[str]:
    """The data acquisition checks of DATA_MODEL §13 that the framework provides: raw
    snapshot files (re-hashed with ``deep``), the append-only triggers of ``raw_snapshot``
    and the running runs."""
    problems: list[str] = []
    with read_transaction(session):
        present = existing_raw_snapshot_triggers(session.connection())
    problems.extend(
        f"trigger: append-only trigger {name} on raw_snapshot is missing"
        for name in RAW_SNAPSHOT_TRIGGER_NAMES
        if name not in present
    )
    files = SnapshotStore(settings.raw_path).check_files(session, deep=deep)
    problems.extend(files[:_MAX_PROBLEMS])
    if len(files) > _MAX_PROBLEMS:
        problems.append("raw_snapshot: … more problems of this kind")
    problems.extend(check_runs(session, settings))
    return problems


_MAX_PROBLEMS = 50


@app.command()
def reindex() -> None:
    """Rebuild both full-text search tables (in batches; the app stays usable)."""
    settings = get_settings()
    _setup(settings)
    _require_database(settings)
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
    )


# --------------------------------------------------------------------------------------
# Data acquisition (docs/COLLECTORS.md §11)
# --------------------------------------------------------------------------------------

_EXIT_CODES = {"succeeded": 0, "partial": 2}


def _sources(settings: Settings) -> SourcesConfig:
    try:
        return sources_of(settings)
    except SourcesError as exc:
        typer.echo(f"error: sources: {exc}", err=True)
        raise typer.Exit(1) from exc


def _require_contact_email(settings: Settings) -> None:
    problem = contact_email_problem(settings.contact_email)
    if problem is not None:
        typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1)


def _transport() -> httpx2.BaseTransport | None:
    """The transport of fixture captures and source checks: the network (tests replace
    this function)."""
    return None


def _progress_line(stats: Mapping[str, Any]) -> str:
    return (
        f"{stats['requests']} requests, {stats['pages_parsed']} pages, "
        f"{stats['entities_created']} created, {stats['entities_updated']} updated, "
        f"{stats['proposals_opened']} proposals opened, {stats['errors']} errors, "
        f"{stats['warnings']} warnings"
    )


def _refused(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(1)


class _RefusedUsage(UsageError):
    """A usage error of ``mdt collect``: exit 1, because 2 means a partial run."""

    exit_code = 1


class _UsageErrorExitsOne(TyperCommand):
    """``mdt collect`` exits 2 only for a ``partial`` run (docs/COLLECTORS.md §6.2, §11), so
    its usage errors (a missing name, an unknown option, a value that is no number) exit 1
    like every other refused start, instead of Click's 2."""

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except UsageError as exc:
            raise _RefusedUsage(exc.format_message(), exc.ctx) from exc


@app.command(cls=_UsageErrorExitsOne)
def collect(
    name: str = typer.Argument(..., help="Collector name (a key of sources.yaml)."),
    mode: str = typer.Option("incremental", "--mode", help="incremental or full."),
    limit: int | None = typer.Option(None, "--limit", help="Stop after N items (N >= 1)."),
    refetch: bool = typer.Option(False, "--refetch", help="Fetch known articles again."),
    recall_sample: int | None = typer.Option(None, "--recall-sample", help="N >= 0 (kmu_news)."),
    recall_seed: int | None = typer.Option(None, "--recall-seed"),
    document: list[str] | None = typer.Option(
        None, "--document", help="Document ID for the tagger (repeatable)."
    ),
) -> None:
    """Run a collector (or the tagger) in the foreground; Ctrl-C cancels it.

    Exits 0 (succeeded), 2 (partial) or 1 (failed, cancelled or refused, invalid
    parameters included).
    """
    settings = get_settings()
    _setup(settings)
    _sources(settings)
    _require_database(settings)
    params: dict[str, Any] = {}
    for key, value in (
        ("limit", limit),
        ("recall_sample", recall_sample),
        ("recall_seed", recall_seed),
    ):
        if value is not None:
            params[key] = value
    if refetch:
        params["refetch"] = True
    if document:
        params["document_ids"] = list(document)
    engine = create_db_engine(settings.sqlalchemy_url)
    factory = create_session_factory(engine, settings)
    try:
        with factory() as session:
            try:
                run_id = start_run(session, settings, RunRequest(name, mode, params, trigger="cli"))
            except NotFoundError as exc:
                raise _refused(f"unknown collector {name}") from exc
            except RunInProgressError as exc:
                raise _refused(
                    f"run {exc.run_id} ({exc.collector}) is running; try again when it has finished"
                ) from exc
            except CollectorUnavailableError as exc:
                raise _refused(exc.message) from exc
            except ValidationError as exc:
                details = "; ".join(
                    f"{path}: {', '.join(messages)}"
                    for path, messages in (exc.details or {}).items()
                )
                raise _refused(details) from exc
        typer.echo(f"run {run_id} ({name}) started")
        status = _execute_in_foreground(factory, settings, run_id)
        with factory() as session:
            run = run_detail(session, settings, run_id)
        _print_run(run)
    finally:
        engine.dispose()
    raise typer.Exit(_EXIT_CODES.get(status, 1))


def _execute_in_foreground(factory: Any, settings: Settings, run_id: str) -> str:
    """Execute the run in a worker thread; Ctrl-C requests cancellation and waits."""
    cancel = threading.Event()
    outcome: dict[str, Any] = {}

    def target() -> None:
        try:
            outcome["status"] = execute_run(
                factory,
                settings,
                run_id,
                cancel=cancel,
                environment=RunEnvironment(
                    progress=lambda stats: typer.echo(_progress_line(stats))
                ),
            )
        except Exception as exc:  # reported below; the run row says what happened
            log.exception("run %s could not be executed", run_id)
            outcome["error"] = exc

    worker = threading.Thread(target=target, name=f"run-{run_id}", daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        typer.echo("cancelling the run …", err=True)
        with factory() as session:
            try:
                request_cancel(session, run_id)
            except Exception:  # the run may have finished meanwhile
                log.debug("cancel request for run %s not recorded", run_id)
        cancel.set()
        worker.join()
    return str(outcome.get("status", "failed"))


def _print_run(run: Mapping[str, Any]) -> None:
    typer.echo(
        f"run {run['id']} ({run['collector']}): {run['status']} after {run['duration_s']} s"
        + (" [replay]" if run["params"].get("replay") else "")
    )
    stats = run["stats"]
    typer.echo("  " + _progress_line(stats))
    typer.echo(
        f"  snapshots {stats['snapshots']}, not modified {stats['not_modified']}, "
        f"robots disallowed {stats['robots_disallowed']}, items seen {stats['items_seen']}, "
        f"revisions {stats['revisions']}, complete listing "
        f"{'yes' if run['complete_listing'] else 'no'}"
    )
    if stats.get("extra"):
        typer.echo("  extra: " + ", ".join(f"{k} {v}" for k, v in sorted(stats["extra"].items())))
    if run["error"]:
        typer.echo(f"  error: {run['error']}")


@runs_app.callback()
def runs(
    ctx: typer.Context,
    collector: str | None = typer.Option(None, "--collector", help="Only this collector."),
    status: str | None = typer.Option(None, "--status", help="Only runs with this status."),
    limit: int = typer.Option(20, "--limit", min=1, max=500, help="How many runs."),
) -> None:
    """List the newest runs (or `mdt runs show <run_id>`)."""
    if ctx.invoked_subcommand is not None:
        return
    settings = get_settings()
    _setup(settings)
    _require_database(settings)
    with _session(settings) as session:
        items, total = list_runs(
            session,
            settings,
            collectors=[collector] if collector else [],
            statuses=[status] if status else [],
            limit=limit,
        )
    if not items:
        typer.echo("no runs")
        return
    for run in items:
        stats = run["stats"]
        typer.echo(
            f"{run['id']}  {run['collector']:<18} {run['status']:<10} {run['trigger']:<3} "
            f"{run['mode']:<11} {run['started_at'][:19]}  {run['duration_s']:>8} s  "
            f"{stats['requests']:>5} req  {stats['entities_created']:>4} new  "
            f"{stats['entities_updated']:>4} upd  {stats['proposals_opened']:>4} prop  "
            f"{stats['errors']:>3} err"
        )
    typer.echo(f"{len(items)} of {total} runs")


@runs_app.command("show")
def runs_show(run_id: str = typer.Argument(..., help="The run's ID.")) -> None:
    """Show one run with its stats and messages."""
    settings = get_settings()
    _setup(settings)
    _require_database(settings)
    with _session(settings) as session:
        try:
            run = run_detail(session, settings, run_id)
        except NotFoundError as exc:
            raise _refused(f"unknown run {run_id}") from exc
        with read_transaction(session):
            messages = session.scalars(
                select(RunMessage).where(RunMessage.run_id == run_id).order_by(RunMessage.id)
            ).all()
            lines = [
                f"  {row.at[:19]} {row.level:<7} {row.code:<24} {row.message}"
                + (f" <{row.url}>" if row.url else "")
                for row in messages
            ]
    _print_run(run)
    typer.echo(
        f"  started {run['started_at']}, finished {run['finished_at']}, trigger {run['trigger']},"
        f" mode {run['mode']}, params {run['params']}, code {run['code_version']}"
    )
    typer.echo(f"messages ({len(lines)}):" if lines else "no messages")
    for line in lines:
        typer.echo(line)


@fixtures_app.command("capture")
def fixtures_capture(
    name: str = typer.Argument(..., help="Collector whose `fixtures` list is captured."),
    only: list[str] | None = typer.Option(None, "--only", help="Only this fixture (repeatable)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing fixture files."),
    out: Path | None = typer.Option(None, "--out", help="Output directory."),
) -> None:
    """Record a collector's fixture list through the polite client (no database rows)."""
    settings = get_settings()
    _setup(settings)
    config = _sources(settings).get(name)
    if config is None:
        raise _refused(f"unknown collector {name}")
    if not config.fixtures:
        raise _refused(f"{name} has no fixtures list in sources.yaml")
    _require_contact_email(settings)
    out_dir = out or default_out_dir(settings, name)
    try:
        results = capture_fixtures(
            config, settings, out_dir, only=only or [], force=force, transport=_transport()
        )
    except ValueError as exc:
        raise _refused(str(exc)) from exc
    for result in results:
        typer.echo(f"{result.name}: {result.state} ({result.detail})")
    typer.echo(f"output directory: {out_dir}")
    if any(result.state in ("failed", "refused") for result in results):
        raise typer.Exit(1)


@sources_app.command("check")
def sources_check(
    names: list[str] | None = typer.Argument(None, help="Collectors (default: all)."),
) -> None:
    """Reachability re-check from this machine: robots.txt and a check URL per host."""
    settings = get_settings()
    _setup(settings)
    sources = _sources(settings)
    selected = list(names or [n for n, c in sources.collectors.items() if not c.builtin])
    unknown = [name for name in selected if sources.get(name) is None]
    if unknown:
        raise _refused(f"unknown collector {', '.join(unknown)}")
    _require_contact_email(settings)
    checks: list[HostCheck] = []
    for name in selected:
        config = sources.collectors[name]
        urls = check_urls(config, lambda: _official_urls(settings))
        if not urls:
            typer.echo(f"{name}: no check URL (set options.check_url in sources.yaml)")
            continue
        checks.extend(check_collector(config, settings, urls, transport=_transport()))
    for item in checks:
        typer.echo(
            f"{item.collector:<18} {item.host:<32} robots {item.robots:<11} "
            f"status {item.status if item.status is not None else '-':<4} "
            f"{item.outcome:<13} {item.duration_ms:>6} ms  final {item.final_url or '-'}"
            + (f"  block: {item.signature}" if item.signature else "")
            + (f"  ({item.robots_reason})" if item.robots in ("blocked", "unavailable") else "")
        )
    failed = [item for item in checks if item.failed]
    if failed:
        typer.echo(f"{len(failed)} host(s) blocked or unreachable", err=True)
        raise typer.Exit(1)


def _official_urls(settings: Settings) -> list[str]:
    """The ``official_urls`` of the live projects (read only; none without a database,
    which is not created either)."""
    problem = database_problem(settings.sqlalchemy_url)
    if problem is not None:
        log.warning("the official URLs of the projects are not checked: %s", problem)
        return []
    try:
        with _session(settings) as session, read_transaction(session):
            rows = session.scalars(
                select(Project.official_urls).where(Project.deleted_at.is_(None))
            ).all()
    except Exception:  # no database yet: C2 has no hosts to check
        log.warning("no database: the official URLs of the projects are not checked")
        return []
    return [str(url) for urls in rows for url in (urls or [])]


# --------------------------------------------------------------------------------------
# mdt import: tabular imports (docs/COLLECTORS.md §9, §11)
# --------------------------------------------------------------------------------------


def _mapping_option(values: list[str]) -> dict[str, str]:
    """``--map COLUMN=FIELD`` options as a mapping."""
    mapping: dict[str, str] = {}
    for value in values:
        column, sep, target = value.partition("=")
        if not sep or not column or not target:
            raise typer.BadParameter(f"{value!r} is not COLUMN=FIELD", param_hint="--map")
        mapping[column] = target
    return mapping


def _print_plan(plan: Plan) -> None:
    stats = plan.stats
    typer.echo(
        f"rows {stats['rows']}: create {stats['create']}, update {stats['update']}, "
        f"unchanged {stats['unchanged']}, with conflicts {stats['conflicts']}, "
        f"errors {stats['errors']}"
    )
    for row in plan.ordered()[:MAX_PLAN_ROWS]:
        target = f" {row.id}" if row.id else ""
        changed = f" ({', '.join(row.changes)})" if row.changes else ""
        typer.echo(f"  row {row.row}: {row.action}{target}{changed}")
        for path, messages in row.errors.items():
            typer.echo(f"    error {path}: {'; '.join(messages)}")
        for conflict in row.conflicts:
            typer.echo(f"    conflict {conflict['field']} ({conflict['reason']}): left unchanged")


@app.command("import")
def import_file(
    file: Path = typer.Argument(..., help="The CSV (UTF-8) or XLSX file."),
    entity_type: str = typer.Option(
        ..., "--type", help="project, service, event, document or organization."
    ),
    sheet: str | None = typer.Option(None, "--sheet", help="XLSX sheet (default: the first)."),
    maps: list[str] = typer.Option(
        [], "--map", help="COLUMN=FIELD, repeatable (default: the suggested mapping)."
    ),
    key: str | None = typer.Option(None, "--key", help="Match rows by id, slug or url."),
    note: str | None = typer.Option(None, "--note", help="Revision note of the writes."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the plan; write nothing."),
) -> None:
    """Import a CSV or XLSX file: the file is stored as an upload first, then planned
    (``--dry-run``) or run on channel ``import``. Exit 1 on invalid input or a failed
    import."""
    settings = get_settings()
    _setup(settings)
    if not file.is_file() or file.stat().st_size == 0:
        typer.echo(f"error: {file} is not a non-empty file", err=True)
        raise typer.Exit(1)
    _require_database(settings)
    with _session(settings) as session:
        try:
            with file.open("rb") as handle:
                chunks = iter(lambda: handle.read(1 << 16), b"")
                upload = SnapshotStore(settings.raw_path).put_upload(session, chunks, file.name)
            preview = preview_import(session, settings, upload.id, entity_type, sheet)
            mapping = _mapping_option(maps) if maps else dict(preview["suggested_mapping"])
            typer.echo(
                "mapping: " + (", ".join(f"{c} → {f}" for c, f in mapping.items()) or "(none)")
            )
            request = ImportRequest(upload.id, entity_type, sheet, mapping, key, note)
            if dry_run:
                _print_plan(dry_run_import(session, settings, request))
                typer.echo("dry run: nothing was written")
                return
            result = run_import(session, settings, request)
        except ValidationError as exc:
            for path, messages in (exc.details or {}).items():
                typer.echo(f"error: {path}: {'; '.join(messages)}", err=True)
            raise typer.Exit(1) from exc
    _print_plan(result.plan)
    run = result.import_run
    typer.echo(f"import {run['id']}: {run['status']} (provenance import:{run['file_label']})")
    if run["status"] != "done":
        typer.echo(f"error: {run['error']}", err=True)
        raise typer.Exit(1)
