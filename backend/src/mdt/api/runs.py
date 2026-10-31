"""Collector runs (docs/API.md §7.2): start, list, detail, fetch log, messages, cancel.

Runs started here execute in a daemon thread of the server (``COLLECTOR_RUN_INLINE``: in
the request) through the app's :class:`~mdt.collectors.runs.RunLauncher`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import Field
from sqlalchemy import func, select

from mdt.api.deps import SessionDep, SettingsDep
from mdt.api.listparams import ListParams
from mdt.api.schemas import Body
from mdt.collectors.client import FETCH_OUTCOMES
from mdt.collectors.run_context import MESSAGE_CODES
from mdt.collectors.runs import (
    RUN_STATUSES,
    RUN_TRIGGERS,
    RunLauncher,
    RunRequest,
    list_runs,
    run_detail,
    sources_of,
)
from mdt.db.models import CollectorRun, FetchLog, RunMessage
from mdt.db.session import read_transaction
from mdt.domain.errors import NotFoundError
from mdt.domain.labels import refs_payload

FETCH_PURPOSES = ("robots", "content")
MESSAGE_LEVELS = ("info", "warning", "error")
_ALL_CODES = tuple(sorted(code for codes in MESSAGE_CODES.values() for code in codes))


class RunBody(Body):
    """``POST /api/runs``."""

    collector: str
    mode: str = "incremental"
    params: dict[str, Any] = Field(default_factory=dict)


class EmptyBody(Body):
    """``POST /api/runs/{id}/cancel``: an empty object."""


def launcher_of(request: Request) -> RunLauncher:
    """The app's run launcher."""
    launcher = request.app.state.runs
    assert isinstance(launcher, RunLauncher)
    return launcher


def post_run(
    body: RunBody, request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """``POST /api/runs`` → ``202 {run}`` (inline: the finished run)."""
    run_id = launcher_of(request).start(
        session, RunRequest(body.collector, body.mode, body.params, trigger="ui")
    )
    return {"run": run_detail(session, settings, run_id)}


def get_runs(request: Request, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/runs``: newest ``started_at`` first."""
    params = ListParams(request.query_params)
    collectors = params.choices("collector", tuple(sources_of(settings).collectors))
    statuses = params.choices("status", RUN_STATUSES)
    triggers = params.choices("trigger", RUN_TRIGGERS)
    items, total = list_runs(
        session,
        settings,
        collectors=collectors,
        statuses=statuses,
        triggers=triggers,
        offset=params.offset,
        limit=params.page_size,
    )
    return params.page_payload(items, total)


def get_run(run_id: str, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/runs/{id}``."""
    return {"run": run_detail(session, settings, run_id)}


def _require_run(session: SessionDep, run_id: str) -> None:
    if session.get(CollectorRun, run_id) is None:
        raise NotFoundError()


def get_fetches(run_id: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/runs/{id}/fetches``: ``FetchLogEntry`` items in request order."""
    params = ListParams(request.query_params)
    conditions = [FetchLog.run_id == run_id]
    if outcomes := params.choices("outcome", FETCH_OUTCOMES):
        conditions.append(FetchLog.outcome.in_(outcomes))
    if purposes := params.choices("purpose", FETCH_PURPOSES):
        conditions.append(FetchLog.purpose.in_(purposes))
    if host := params.raw("host"):
        conditions.append(FetchLog.host == host.strip().lower())
    with read_transaction(session):
        _require_run(session, run_id)
        total = session.scalar(select(func.count()).select_from(FetchLog).where(*conditions))
        rows = session.scalars(
            select(FetchLog)
            .where(*conditions)
            .order_by(FetchLog.id)
            .offset(params.offset)
            .limit(params.page_size)
        ).all()
        items = [
            {
                "id": row.id,
                "at": row.at,
                "method": row.method,
                "url": row.url,
                "host": row.host,
                "purpose": row.purpose,
                "attempt": row.attempt,
                "status": row.status,
                "outcome": row.outcome,
                "bytes": row.bytes,
                "duration_ms": row.duration_ms,
                "raw_snapshot_id": row.raw_snapshot_id,
                "retry_after_s": row.retry_after_s,
                "error": row.error,
            }
            for row in rows
        ]
    return params.page_payload(items, int(total or 0))


def get_messages(run_id: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/runs/{id}/messages``: ``RunMessage`` items in order, with ``refs``."""
    params = ListParams(request.query_params)
    conditions = [RunMessage.run_id == run_id]
    if levels := params.choices("level", MESSAGE_LEVELS):
        conditions.append(RunMessage.level.in_(levels))
    if codes := params.choices("code", _ALL_CODES):
        conditions.append(RunMessage.code.in_(codes))
    with read_transaction(session):
        _require_run(session, run_id)
        total = session.scalar(select(func.count()).select_from(RunMessage).where(*conditions))
        rows = session.scalars(
            select(RunMessage)
            .where(*conditions)
            .order_by(RunMessage.id)
            .offset(params.offset)
            .limit(params.page_size)
        ).all()
        items = [
            {
                "id": row.id,
                "at": row.at,
                "level": row.level,
                "code": row.code,
                "message": row.message,
                "url": row.url,
                "raw_snapshot_id": row.raw_snapshot_id,
                "subject_id": row.subject_id,
                "details": dict(row.details or {}),
            }
            for row in rows
        ]
        refs = refs_payload(session, [row.subject_id for row in rows])
    return {**params.page_payload(items, int(total or 0)), "refs": refs}


def cancel_run(
    run_id: str, body: EmptyBody, request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """``POST /api/runs/{id}/cancel``: the run with ``cancel_requested_at`` set."""
    launcher_of(request).cancel(session, run_id)
    return {"run": run_detail(session, settings, run_id)}


def register(app: FastAPI) -> None:
    """Add the run routes."""
    app.add_api_route("/api/runs", post_run, methods=["POST"], status_code=202)
    app.add_api_route("/api/runs", get_runs, methods=["GET"])
    app.add_api_route("/api/runs/{run_id}", get_run, methods=["GET"])
    app.add_api_route("/api/runs/{run_id}/fetches", get_fetches, methods=["GET"])
    app.add_api_route("/api/runs/{run_id}/messages", get_messages, methods=["GET"])
    app.add_api_route("/api/runs/{run_id}/cancel", cancel_run, methods=["POST"])
