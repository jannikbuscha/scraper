"""Collectors (docs/API.md §7.2): ``GET /api/collectors`` and ``GET /api/collectors/{name}``.

A collector is listed when ``sources.yaml`` configures it and a module implements it
(docs/COLLECTORS.md §2).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mdt.api.deps import SessionDep, SettingsDep
from mdt.collectors.base import Collector
from mdt.collectors.runs import (
    availability,
    implemented,
    is_replay,
    lookup,
    serialize_runs,
    sources_of,
)
from mdt.collectors.sources import CollectorConfig
from mdt.config import Settings
from mdt.db.models import CollectorRun, Proposal, SourceObservation
from mdt.db.session import read_transaction

RECENT_RUNS = 10


def collector_payload(
    session: Session, settings: Settings, config: CollectorConfig, collector: Collector
) -> dict[str, Any]:
    """The ``Collector`` object of docs/API.md §7.2 (inside a read transaction)."""
    reason = availability(config, settings, replay=is_replay(settings))
    last = session.scalars(
        select(CollectorRun)
        .where(CollectorRun.collector == config.name)
        .order_by(CollectorRun.started_at.desc(), CollectorRun.id.desc())
        .limit(1)
    ).first()
    running = session.scalar(
        select(CollectorRun.id).where(
            CollectorRun.collector == config.name, CollectorRun.status == "running"
        )
    )
    present = session.execute(
        select(SourceObservation.present, func.count())
        .where(SourceObservation.collector == config.name)
        .group_by(SourceObservation.present)
    ).all()
    counts = {bool(flag): int(count) for flag, count in present}
    open_proposals = session.scalar(
        select(func.count())
        .select_from(Proposal)
        .where(Proposal.collector == config.name, Proposal.state == "open")
    )
    return {
        "name": config.name,
        "label": config.label,
        "source": config.source,
        "builtin": config.builtin,
        "enabled": config.enabled,
        "available": reason is None,
        "unavailable_reason": reason,
        "needs_server_check": config.needs_server_check,
        "modes": list(collector.MODES),
        "params": sorted(collector.PARAMS),
        "hosts": [
            {"host": host, "min_interval_s": interval}
            for host, interval in sorted(config.host_intervals.items())
        ],
        "exclude_hosts": sorted(config.exclude_hosts),
        "licence": {"code": config.licence.code, "statement": config.licence.statement},
        "declaration": {
            entity_type: {
                "creates": declaration.creates,
                "writes": sorted(declaration.writes),
                "propose_only": sorted(declaration.propose_only),
                "discontinued": declaration.discontinued,
            }
            for entity_type, declaration in collector.DECLARATION.items()
        },
        "last_run": serialize_runs(session, settings, [last])[0] if last else None,
        "running_run_id": running,
        "observations": {
            "total": sum(counts.values()),
            "present": counts.get(True, 0),
            "missing": counts.get(False, 0),
        },
        "open_proposals": int(open_proposals or 0),
    }


def get_collectors(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/collectors``."""
    found = implemented(sources_of(settings))
    with read_transaction(session):
        return {
            "collectors": [
                collector_payload(session, settings, config, collector)
                for config, collector in found.values()
            ]
        }


def get_collector(name: str, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/collectors/{name}``: the collector and its 10 newest runs."""
    config, collector = lookup(settings, name)
    with read_transaction(session):
        rows = session.scalars(
            select(CollectorRun)
            .where(CollectorRun.collector == name)
            .order_by(CollectorRun.started_at.desc(), CollectorRun.id.desc())
            .limit(RECENT_RUNS)
        ).all()
        return {
            "collector": collector_payload(session, settings, config, collector),
            "recent_runs": serialize_runs(session, settings, rows),
        }


def register(app: FastAPI) -> None:
    """Add the collector routes."""
    app.add_api_route("/api/collectors", get_collectors, methods=["GET"])
    app.add_api_route("/api/collectors/{name}", get_collector, methods=["GET"])
