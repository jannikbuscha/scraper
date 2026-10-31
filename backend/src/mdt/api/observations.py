"""Source observations (docs/API.md §7.5): what the collectors saw per key, read-only.

Observations are bound by the collectors' matching rules and by accepted ``create_entity``
proposals (docs/DATA_MODEL.md §15.3, §16.4); there is no endpoint to bind them by hand.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from mdt.api.deps import SessionDep, SettingsDep
from mdt.api.listparams import ListParams
from mdt.collectors.runs import sources_of
from mdt.db.session import read_transaction
from mdt.domain.labels import refs_payload
from mdt.domain.observations import ObservationFilter, list_observations
from mdt.domain.registry import generic_types


def get_observations(
    request: Request, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """``GET /api/observations``: ``Observation`` items ordered by collector and key, with
    ``refs`` for the bound records."""
    params = ListParams(request.query_params)
    flt = ObservationFilter(
        collectors=params.choices("collector", tuple(sources_of(settings).collectors)),
        entity_types=params.choices("entity_type", tuple(spec.name for spec in generic_types())),
        subject_id=params.raw("subject_id"),
        present=params.flag("present"),
        bound=params.flag("bound"),
        q=params.raw("q"),
    )
    with read_transaction(session):
        items, total = list_observations(session, flt, offset=params.offset, limit=params.page_size)
        refs = refs_payload(session, [item["subject_id"] for item in items])
    return {**params.page_payload(items, total), "refs": refs}


def register(app: FastAPI) -> None:
    """Add the observation route."""
    app.add_api_route("/api/observations", get_observations, methods=["GET"])
