"""Collector runs: start, execution, stale recovery, cancellation and end status
(docs/COLLECTORS.md §6, docs/DATA_MODEL.md §14.2).

* **Start** (:func:`start_run`): the configuration is checked (collector configured,
  implemented and enabled; ``CONTACT_EMAIL`` valid unless the collector is built in or the
  run replays fixtures; mode and parameters valid), stale runs are recovered and the run is
  inserted as ``running`` in one write unit. A second running run is refused
  (:class:`RunInProgressError`; the partial unique index guards it too).
* **Execution** (:func:`execute_run`): in the CLI process (foreground) or a daemon thread of
  the server (:class:`RunLauncher`; with ``COLLECTOR_RUN_INLINE`` in the request). The
  collector runs with its :class:`~mdt.collectors.run_context.ActiveRun`; a heartbeat thread
  keeps ``heartbeat_at`` fresh and notices cancel requests of other processes.
* **Finish:** the disappearance step after a complete listing of a run that was not
  cancelled, the duplicate detection when the run reconciled anything, then the end status:
  ``failed`` (fatal error), ``cancelled``, ``partial`` (any error-level message, which every
  failed content request writes) or ``succeeded``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx2
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from mdt import __version__
from mdt.collectors import registry
from mdt.collectors.base import RUN_MODES, Collector, FatalRunError
from mdt.collectors.client import RunCancelled
from mdt.collectors.errors import CollectorUnavailableError, RunInProgressError
from mdt.collectors.replay import ReplayTransport
from mdt.collectors.run_context import ActiveRun, Heartbeat, Progress, empty_stats
from mdt.collectors.sources import CollectorConfig, SourcesConfig, load_sources
from mdt.collectors.throttle import Clock, HostThrottle
from mdt.config import Settings, contact_email_problem
from mdt.db.models import CollectorRun as RunRow
from mdt.db.models import RunMessage
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.clock import format_timestamp, parse_timestamp, utc_now
from mdt.domain.errors import InvalidStateError, NotFoundError, Problems
from mdt.domain.ids import id_prefix, new_id

log = logging.getLogger("mdt.collectors")

RUN_STATUSES = ("running", "succeeded", "partial", "failed", "cancelled")
RUN_TRIGGERS = ("cli", "ui")
STALE_ERROR = "interrupted: no heartbeat since {} (the process ended or restarted)"
MAX_ERROR_CHARS = 2000
SHUTDOWN_WAIT_S = 10.0
#: Codebook files that are part of a run's ``config_hash`` (docs/COLLECTORS.md §7.7, §7.9).
CODEBOOK_FILES = ("collector_mappings.yaml", "event_patterns.yaml")


@dataclass(frozen=True)
class RunRequest:
    """What a run is started with."""

    collector: str
    mode: str = "incremental"
    params: Mapping[str, Any] = field(default_factory=dict)
    trigger: str = "ui"


@dataclass
class RunEnvironment:
    """How a run executes besides its request (tests inject transports and clocks)."""

    transport: httpx2.BaseTransport | None = None
    clock: Clock | None = None
    throttle: HostThrottle | None = None
    progress: Progress | None = None
    heartbeat_s: float | None = None
    cancel_poll_s: float | None = None


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


def sources_of(settings: Settings) -> SourcesConfig:
    """The validated ``sources.yaml`` of the settings."""
    return load_sources(settings.sources_path)


def implemented(sources: SourcesConfig) -> dict[str, tuple[CollectorConfig, Collector]]:
    """The configured collectors that have a module, in file order."""
    found: dict[str, tuple[CollectorConfig, Collector]] = {}
    for name, config in sources.collectors.items():
        collector = registry.resolve(name)
        if collector is not None:
            found[name] = (config, collector)
    return found


def lookup(settings: Settings, name: str) -> tuple[CollectorConfig, Collector]:
    """The configuration and module of ``name`` (404 if it is not both)."""
    config = sources_of(settings).get(name)
    collector = registry.resolve(name) if config is not None else None
    if config is None or collector is None:
        raise NotFoundError(f"Unknown collector {name}")
    return config, collector


def is_replay(settings: Settings, transport: httpx2.BaseTransport | None = None) -> bool:
    """Whether runs answer from fixtures: ``COLLECTOR_REPLAY_DIR`` or a replay transport."""
    return settings.replay_path is not None or isinstance(transport, ReplayTransport)


def availability(config: CollectorConfig, settings: Settings, *, replay: bool) -> str | None:
    """Why the collector cannot be started (``disabled``, ``contact_email_missing``), or
    None (docs/COLLECTORS.md §4.4)."""
    if not config.enabled:
        return "disabled"
    if not config.builtin and not replay and contact_email_problem(settings.contact_email):
        return "contact_email_missing"
    return None


def check_available(config: CollectorConfig, settings: Settings, *, replay: bool) -> None:
    """Raise :class:`CollectorUnavailableError` if the collector cannot be started."""
    reason = availability(config, settings, replay=replay)
    if reason == "disabled":
        raise CollectorUnavailableError(reason, f"The collector {config.name} is disabled")
    if reason == "contact_email_missing":
        problem = contact_email_problem(settings.contact_email) or ""
        raise CollectorUnavailableError(reason, problem)


def validate_request(collector: Collector, mode: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Check mode and parameters (docs/COLLECTORS.md §6.4); ``400 validation_error``
    otherwise. Returns the parameters as recorded."""
    problems = Problems()
    if mode not in RUN_MODES:
        problems.add("mode", f"must be one of {', '.join(RUN_MODES)}")
    clean: dict[str, Any] = {}
    for name, value in params.items():
        path = f"params.{name}"
        if name not in registry.KNOWN_PARAMS:
            problems.add(path, "unknown parameter")
        elif name not in collector.PARAMS:
            problems.add(path, f"not supported by {collector.NAME}")
        elif name == "refetch":
            if not isinstance(value, bool):
                problems.add(path, "must be true or false")
        elif name == "document_ids":
            if not isinstance(value, list) or not value or len(value) > 500:
                problems.add(path, "must be a list of 1 to 500 document IDs")
            elif any(not isinstance(item, str) or id_prefix(item) != "doc" for item in value):
                problems.add(path, "must contain document IDs only")
        elif isinstance(value, bool) or not isinstance(value, int):
            problems.add(path, "must be an integer")
        elif name == "limit" and value < 1:
            problems.add(path, "must be at least 1")
        elif name == "recall_sample" and value < 0:
            problems.add(path, "must be at least 0")
        if name in registry.KNOWN_PARAMS:
            clean[name] = (
                list(value) if name == "document_ids" and isinstance(value, list) else value
            )
    problems.raise_if_any()
    return clean


def code_version() -> str:
    """App version and ``GIT_COMMIT`` (e.g. ``0.1.0+3f2c1a9``)."""
    commit = os.environ.get("GIT_COMMIT", "").strip()
    if not commit or commit == "unknown":
        return __version__
    dirty = "-dirty" if commit.endswith("-dirty") else ""
    return f"{__version__}+{commit.removesuffix('-dirty')[:7]}{dirty}"


def config_hash(config: CollectorConfig, settings: Settings) -> str:
    """SHA-256 of the collector's ``sources.yaml`` entry (with the defaults) and of the
    codebook files collectors use (docs/DATA_MODEL.md §14.2)."""
    files: dict[str, str | None] = {}
    for name in CODEBOOK_FILES:
        path = settings.codebook_path / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    text = json.dumps({"entry": config.entry_hash, "codebook": files}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Start, stale runs, cancel
# --------------------------------------------------------------------------------------


def _recover_stale(session: Session, settings: Settings, now: str) -> list[str]:
    """Inside a write unit: fail the running runs whose heartbeat is too old."""
    cutoff = format_timestamp(parse_timestamp(now) - timedelta(seconds=settings.run_stale_after_s))
    stale = session.execute(
        select(RunRow.id, func.coalesce(RunRow.heartbeat_at, RunRow.started_at)).where(
            RunRow.status == "running",
            func.coalesce(RunRow.heartbeat_at, RunRow.started_at) < cutoff,
        )
    ).all()
    for run_id, beat in stale:
        session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == "running")
            .values(status="failed", finished_at=now, error=STALE_ERROR.format(beat))
        )
        log.warning("run %s recovered as failed (no heartbeat since %s)", run_id, beat)
    return [run_id for run_id, _ in stale]


def recover_stale_runs(session: Session, settings: Settings) -> list[str]:
    """Fail the stale runs (docs/COLLECTORS.md §6.3); returns their IDs."""
    with write_transaction(session):
        return _recover_stale(session, settings, utc_now())


def running_run(session: Session) -> RunRow | None:
    """The running run, if any (inside the caller's transaction)."""
    return session.scalars(select(RunRow).where(RunRow.status == "running")).first()


def start_run(
    session: Session,
    settings: Settings,
    request: RunRequest,
    *,
    transport: httpx2.BaseTransport | None = None,
) -> str:
    """Check the request and insert the run as ``running`` (docs/COLLECTORS.md §6.1)."""
    if request.trigger not in RUN_TRIGGERS:
        raise ValueError(f"unknown trigger {request.trigger!r}")
    config, collector = lookup(settings, request.collector)
    replay = is_replay(settings, transport)
    params = validate_request(collector, request.mode, request.params)
    check_available(config, settings, replay=replay)
    if replay:
        params["replay"] = True
    run_id = new_id("run")
    values = {
        "id": run_id,
        "collector": config.name,
        "trigger": request.trigger,
        "mode": request.mode,
        "params": params,
        "status": "running",
        "complete_listing": False,
        "stats": empty_stats(),
        "code_version": code_version(),
        "config_hash": config_hash(config, settings),
    }
    try:
        with write_transaction(session):
            now = utc_now()
            _recover_stale(session, settings, now)
            other = running_run(session)
            if other is not None:
                raise RunInProgressError(other.id, other.collector)
            session.execute(insert(RunRow).values(started_at=now, heartbeat_at=now, **values))
    except IntegrityError:
        with read_transaction(session):
            other = running_run(session)
            if other is None:
                raise
            raise RunInProgressError(other.id, other.collector) from None
    return run_id


def request_cancel(session: Session, run_id: str) -> None:
    """Record a cancel request (``409 invalid_state`` for a finished run)."""
    with write_transaction(session):
        row = session.get(RunRow, run_id)
        if row is None:
            raise NotFoundError()
        if row.status != "running":
            raise InvalidStateError(row.status, "Only a running run can be cancelled")
        if row.cancel_requested_at is None:
            session.execute(
                update(RunRow).where(RunRow.id == run_id).values(cancel_requested_at=utc_now())
            )


# --------------------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------------------


def execute_run(
    session_factory: sessionmaker[Session],
    settings: Settings,
    run_id: str,
    *,
    cancel: threading.Event | None = None,
    environment: RunEnvironment | None = None,
) -> str:
    """Execute a started run to its end and return its end status."""
    env = environment or RunEnvironment()
    cancel = cancel or threading.Event()
    with session_factory() as session:
        with read_transaction(session):
            row = session.get(RunRow, run_id)
            if row is None or row.status != "running":
                raise InvalidStateError(row.status if row else "missing", "The run is not running")
            mode, params, name = row.mode, dict(row.params or {}), row.collector
        try:
            run = _prepare(session, settings, run_id, name, mode, params, cancel, env)
        except Exception as exc:
            log.exception("run %s (%s) could not start", run_id, name)
            _fail_unstarted(session, run_id, f"the run could not start: {describe_error(exc)}")
            return "failed"
        heartbeat_options: dict[str, float] = {}
        if env.heartbeat_s is not None:
            heartbeat_options["interval"] = env.heartbeat_s
        if env.cancel_poll_s is not None:
            heartbeat_options["poll"] = env.cancel_poll_s
        heartbeat = Heartbeat(session_factory, run_id, cancel, **heartbeat_options)
        heartbeat.start()
        try:
            status, error = _run_to_end(run)
        finally:
            heartbeat.stop()
            run.client.close()
        _finalize(run, status, error)
        return status


def _prepare(
    session: Session,
    settings: Settings,
    run_id: str,
    name: str,
    mode: str,
    params: Mapping[str, Any],
    cancel: threading.Event,
    env: RunEnvironment,
) -> ActiveRun:
    config, collector = lookup(settings, name)
    transport = env.transport
    if transport is None and settings.replay_path is not None:
        transport = ReplayTransport([settings.replay_path])
    return ActiveRun(
        run_id=run_id,
        mode=mode,
        params={key: value for key, value in params.items() if key != "replay"},
        implementation=collector,
        config=config,
        settings=settings,
        session=session,
        cancel=cancel,
        transport=transport,
        replay=bool(params.get("replay")),
        clock=env.clock,
        throttle=env.throttle,
        progress=env.progress,
    )


def describe_error(exc: BaseException) -> str:
    """``<type>: <message>`` of an exception; a database error without its SQL."""
    if isinstance(exc, StatementError) and exc.orig is not None:
        exc = exc.orig
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _fail_unstarted(session: Session, run_id: str, error: str) -> None:
    """End a run that could not start as ``failed`` (with its ``fatal`` message)."""
    now = utc_now()
    error = error[:MAX_ERROR_CHARS]
    with write_transaction(session):
        session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == "running")
            .values(status="failed", finished_at=now, error=error)
        )
        session.execute(
            insert(RunMessage).values(
                run_id=run_id, at=now, level="error", code="fatal", message=error, details={}
            )
        )


def _run_to_end(run: ActiveRun) -> tuple[str, str | None]:
    """Run the collector and the finish steps; return the end status and fatal error."""
    fatal: str | None = None
    try:
        run.implementation.run(run)
    except RunCancelled:
        pass
    except FatalRunError as exc:
        fatal = str(exc) or type(exc).__name__
    except Exception as exc:
        log.exception("run %s (%s) failed", run.run_id, run.collector)
        fatal = f"unexpected error: {describe_error(exc)}"
    cancelled = run.cancelled()
    try:
        run.finish_steps(cancelled=cancelled)
    except Exception as exc:
        log.exception("finish step of run %s (%s) failed", run.run_id, run.collector)
        fatal = fatal or f"finish step failed: {describe_error(exc)}"
    if fatal is not None:
        fatal = fatal[:MAX_ERROR_CHARS]
        run.message("error", "fatal", fatal)
        return "failed", fatal
    if cancelled:
        return "cancelled", None
    return ("partial" if run.stats["errors"] else "succeeded"), None


def _finalize(run: ActiveRun, status: str, error: str | None) -> None:
    run.flush()
    now = utc_now()
    with write_transaction(run.session):
        run.session.execute(
            update(RunRow)
            .where(RunRow.id == run.run_id, RunRow.status == "running")
            .values(
                status=status,
                finished_at=now,
                heartbeat_at=now,
                error=error,
                stats={**run.stats, "extra": dict(run.stats["extra"])},
                complete_listing=run.complete,
            )
        )


# --------------------------------------------------------------------------------------
# The server's runs
# --------------------------------------------------------------------------------------


class RunLauncher:
    """Runs started by this server process: a daemon thread per run (or the request itself
    with ``COLLECTOR_RUN_INLINE``); at shutdown its running run is asked to stop."""

    def __init__(self, settings: Settings, session_factory: sessionmaker[Session]) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._lock = threading.Lock()
        self._runs: dict[str, tuple[threading.Thread | None, threading.Event]] = {}

    def start(self, session: Session, request: RunRequest) -> str:
        """Start a run; returns its ID once it is running (inline: once it has finished)."""
        run_id = start_run(session, self.settings, request)
        cancel = threading.Event()
        if self.settings.collector_run_inline:
            with self._lock:
                self._runs[run_id] = (None, cancel)
            try:
                execute_run(self.session_factory, self.settings, run_id, cancel=cancel)
            finally:
                with self._lock:
                    self._runs.pop(run_id, None)
            return run_id
        thread = threading.Thread(
            target=self._execute, args=(run_id, cancel), name=f"run-{run_id}", daemon=True
        )
        with self._lock:
            self._runs[run_id] = (thread, cancel)
        thread.start()
        return run_id

    def _execute(self, run_id: str, cancel: threading.Event) -> None:
        try:
            execute_run(self.session_factory, self.settings, run_id, cancel=cancel)
        except Exception:
            log.exception("run %s could not be executed", run_id)
        finally:
            with self._lock:
                self._runs.pop(run_id, None)

    def cancel(self, session: Session, run_id: str) -> None:
        """Record a cancel request and wake the run if this process executes it."""
        request_cancel(session, run_id)
        with self._lock:
            entry = self._runs.get(run_id)
        if entry is not None:
            entry[1].set()

    def shutdown(self, timeout: float = SHUTDOWN_WAIT_S) -> None:
        """Ask the running runs to stop and wait up to ``timeout`` seconds."""
        with self._lock:
            entries = list(self._runs.items())
        for _run_id, (_thread, cancel) in entries:
            cancel.set()
        for _run_id, (thread, _cancel) in entries:
            if thread is not None:
                thread.join(timeout)


# --------------------------------------------------------------------------------------
# Reading runs (API §7.2, CLI)
# --------------------------------------------------------------------------------------


def message_counts(session: Session, run_ids: Sequence[str]) -> dict[str, dict[str, int]]:
    """Stored messages per run and level (inside the caller's transaction)."""
    counts = {run_id: {"error": 0, "warning": 0, "info": 0} for run_id in run_ids}
    if not run_ids:
        return counts
    rows = session.execute(
        select(RunMessage.run_id, RunMessage.level, func.count())
        .where(RunMessage.run_id.in_(run_ids))
        .group_by(RunMessage.run_id, RunMessage.level)
    )
    for run_id, level, count in rows:
        counts[run_id][level] = int(count)
    return counts


def duration_s(row: RunRow, now: str | None = None) -> float:
    """Seconds from start to finish (running runs: to now)."""
    end = row.finished_at or now or utc_now()
    delta = parse_timestamp(end) - parse_timestamp(row.started_at)
    return round(max(0.0, delta.total_seconds()), 1)


def run_payload(
    row: RunRow, *, label: str | None, counts: Mapping[str, int], now: str | None = None
) -> dict[str, Any]:
    """The ``Run`` object of docs/API.md §7.2."""
    stats = {**empty_stats(), **dict(row.stats or {})}
    return {
        "id": row.id,
        "collector": row.collector,
        "collector_label": label,
        "trigger": row.trigger,
        "mode": row.mode,
        "params": dict(row.params or {}),
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "heartbeat_at": row.heartbeat_at,
        "duration_s": duration_s(row, now),
        "cancel_requested_at": row.cancel_requested_at,
        "complete_listing": bool(row.complete_listing),
        "stats": stats,
        "error": row.error,
        "code_version": row.code_version,
        "config_hash": row.config_hash,
        "message_counts": dict(counts),
    }


def serialize_runs(
    session: Session, settings: Settings, rows: Sequence[RunRow]
) -> list[dict[str, Any]]:
    """``Run`` objects for rows read in the caller's transaction."""
    labels = labels_of(settings)
    counts = message_counts(session, [row.id for row in rows])
    now = utc_now()
    return [
        run_payload(row, label=labels.get(row.collector), counts=counts[row.id], now=now)
        for row in rows
    ]


def run_detail(session: Session, settings: Settings, run_id: str) -> dict[str, Any]:
    """The ``Run`` object of one run (404 if unknown)."""
    with read_transaction(session):
        row = session.get(RunRow, run_id)
        if row is None:
            raise NotFoundError()
        return serialize_runs(session, settings, [row])[0]


def list_runs(
    session: Session,
    settings: Settings,
    *,
    collectors: Sequence[str] = (),
    statuses: Sequence[str] = (),
    triggers: Sequence[str] = (),
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Runs, newest ``started_at`` first, and their total under the filters."""
    conditions = []
    if collectors:
        conditions.append(RunRow.collector.in_(collectors))
    if statuses:
        conditions.append(RunRow.status.in_(statuses))
    if triggers:
        conditions.append(RunRow.trigger.in_(triggers))
    with read_transaction(session):
        total = session.scalar(select(func.count()).select_from(RunRow).where(*conditions))
        rows = session.scalars(
            select(RunRow)
            .where(*conditions)
            .order_by(RunRow.started_at.desc(), RunRow.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return serialize_runs(session, settings, rows), int(total or 0)


def labels_of(settings: Settings) -> dict[str, str]:
    """Collector labels from ``sources.yaml`` (empty if the file cannot be read)."""
    try:
        return {name: config.label for name, config in sources_of(settings).collectors.items()}
    except ValueError:
        return {}


def runs_summary(session: Session) -> dict[str, Any]:
    """``runs`` of ``GET /api/stats``: the running run and the last finished one."""
    with read_transaction(session):
        running = running_run(session)
        last = session.scalars(
            select(RunRow)
            .where(RunRow.status != "running")
            .order_by(RunRow.finished_at.desc(), RunRow.id.desc())
            .limit(1)
        ).first()
        return {
            "running": None
            if running is None
            else {
                "id": running.id,
                "collector": running.collector,
                "started_at": running.started_at,
            },
            "last_finished": None
            if last is None
            else {
                "id": last.id,
                "collector": last.collector,
                "status": last.status,
                "finished_at": last.finished_at,
            },
        }


def check_runs(session: Session, settings: Settings) -> list[str]:
    """Integrity problems of the runs (DATA_MODEL §13): more than one running run, and
    running runs whose heartbeat is older than the stale limit."""
    problems: list[str] = []
    now = parse_timestamp(utc_now())
    with read_transaction(session):
        running = session.scalars(select(RunRow).where(RunRow.status == "running")).all()
    if len(running) > 1:
        problems.append(f"run: {len(running)} runs are running at once")
    for row in running:
        beat = parse_timestamp(row.heartbeat_at or row.started_at)
        if (now - beat).total_seconds() > settings.run_stale_after_s:
            since = f"{beat:%Y-%m-%d %H:%M:%S} UTC"
            problems.append(f"run: {row.id} ({row.collector}) has no heartbeat since {since}")
    return problems
