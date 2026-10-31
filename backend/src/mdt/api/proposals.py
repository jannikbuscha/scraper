"""Proposals (docs/API.md §7.4): list, summary, detail, accept, reject and bulk decisions.

Decisions write on channel ``ui`` with ``revision.proposal_id`` (docs/DATA_MODEL.md §16.4);
the domain functions in :mod:`mdt.domain.proposal_actions` validate the values.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from mdt.api.deps import SessionDep, SettingsDep
from mdt.api.listparams import ListParams
from mdt.api.schemas import Body
from mdt.collectors.runs import sources_of
from mdt.domain.errors import ValidationError
from mdt.domain.proposal_actions import accept_proposal, bulk_decide, reject_proposal
from mdt.domain.proposal_queries import (
    SORTS,
    ProposalFilter,
    list_proposals,
    proposal_detail,
    proposal_item,
    proposal_summary,
)
from mdt.domain.proposals import KINDS, STATES
from mdt.domain.registry import TABLE_TYPES


class AcceptBody(Body):
    """``POST /api/proposals/{id}/accept``: ``values`` for edit & accept, ``match_id`` to
    link a new record's source entry to an existing record."""

    values: dict[str, Any] | None = None
    match_id: str | None = None
    note: str | None = None


class RejectBody(Body):
    """``POST /api/proposals/{id}/reject``: the note is required (checked by the domain)."""

    note: str | None = None


class BulkDecisionBody(Body):
    """``POST /api/proposals/bulk``."""

    ids: list[str]
    action: str
    note: str | None = None


def _filter(params: ListParams, collectors: tuple[str, ...]) -> ProposalFilter:
    state = params.raw("state")
    if state is None:
        states = ["open"]
    elif state == "all":
        states = []
    else:
        states = params.choices("state", STATES)
    return ProposalFilter(
        states=states,
        kinds=params.choices("kind", KINDS),
        collectors=params.choices("collector", collectors),
        entity_types=params.choices("entity_type", TABLE_TYPES),
        subject_id=params.raw("subject_id"),
        run_id=params.raw("run_id"),
        field=params.raw("field"),
    )


def get_proposals(request: Request, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/proposals``: ``Proposal`` items (default: open, newest last seen first)
    with ``refs``."""
    params = ListParams(request.query_params)
    flt = _filter(params, tuple(sources_of(settings).collectors))
    sort = params.raw("sort") or SORTS[0]
    if sort not in SORTS:
        raise ValidationError.single("sort", f"must be one of {', '.join(SORTS)}")
    items, total, refs = list_proposals(
        session, flt, sort=sort, offset=params.offset, limit=params.page_size
    )
    return {**params.page_payload(items, total), "refs": refs}


def get_summary(session: SessionDep) -> dict[str, Any]:
    """``GET /api/proposals/summary``: open counts and the pattern precision."""
    return proposal_summary(session)


def get_proposal(proposal_id: str, session: SessionDep) -> dict[str, Any]:
    """``GET /api/proposals/{id}``: the proposal with ``refs`` and, for a text version,
    both texts."""
    return proposal_detail(session, proposal_id)


def accept(proposal_id: str, body: AcceptBody, session: SessionDep) -> dict[str, Any]:
    """``POST /api/proposals/{id}/accept`` (accept, edit & accept, link to existing)."""
    decision = accept_proposal(
        session, proposal_id, values=body.values, match_id=body.match_id, note=body.note
    )
    return {
        "proposal": proposal_item(session, proposal_id),
        "changed": decision.changed,
        "result_id": decision.result_id,
        "revision_ids": decision.revision_ids,
        "batch_id": decision.batch_id,
    }


def reject(proposal_id: str, body: RejectBody, session: SessionDep) -> dict[str, Any]:
    """``POST /api/proposals/{id}/reject``: the rejected proposal."""
    reject_proposal(session, proposal_id, body.note)
    return {"proposal": proposal_item(session, proposal_id)}


def bulk(body: BulkDecisionBody, session: SessionDep) -> dict[str, Any]:
    """``POST /api/proposals/bulk``: one result per proposal."""
    result = bulk_decide(session, body.ids, body.action, body.note)
    return {"batch_id": result.batch_id, "results": result.results}


def register(app: FastAPI) -> None:
    """Add the proposal routes (fixed sub-paths before ``{proposal_id}``)."""
    app.add_api_route("/api/proposals", get_proposals, methods=["GET"])
    app.add_api_route("/api/proposals/summary", get_summary, methods=["GET"])
    app.add_api_route("/api/proposals/bulk", bulk, methods=["POST"])
    app.add_api_route("/api/proposals/{proposal_id}", get_proposal, methods=["GET"])
    app.add_api_route("/api/proposals/{proposal_id}/accept", accept, methods=["POST"])
    app.add_api_route("/api/proposals/{proposal_id}/reject", reject, methods=["POST"])
