"""Merge and unmerge of projects and services (docs/API.md §7.6): merge preview, merge,
unmerge. Both writes run on channel ``merge`` (docs/DATA_MODEL.md §18)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Query
from pydantic import Field

from mdt.api.deps import SessionDep
from mdt.api.schemas import Body
from mdt.domain.merge import merge, merge_preview, unmerge
from mdt.domain.serialize import get_item

ENTITY = "/api/entities/{entity_type}/{entity_id}"


class MergeBody(Body):
    """``POST …/{id}/merge``: ``{id}`` is the survivor; ``fields`` maps field names to
    ``survivor`` (default), ``merged`` or ``union``."""

    merged_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
    proposal_id: str | None = None


class UnmergeBody(Body):
    """``POST …/{id}/unmerge``: ``{id}`` is the merged record."""

    note: str | None = None


def get_merge_preview(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
    merged_id: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    """``GET …/{id}/merge-preview?merged_id=``: differing fields, references to move and
    conflicts."""
    return merge_preview(session, entity_type, entity_id, merged_id)


def post_merge(
    entity_type: str, entity_id: str, body: MergeBody, session: SessionDep
) -> dict[str, Any]:
    """``POST …/{id}/merge``: the survivor after the merge."""
    result = merge(
        session, entity_type, entity_id, body.merged_id, body.fields, body.note, body.proposal_id
    )
    return {
        "item": get_item(session, entity_type, entity_id),
        "merge_id": result.merge_id,
        "batch_id": result.batch_id,
        "revision_ids": result.revision_ids,
    }


def post_unmerge(
    entity_type: str, entity_id: str, body: UnmergeBody, session: SessionDep
) -> dict[str, Any]:
    """``POST …/{id}/unmerge``: the restored record and the references left as they are."""
    result = unmerge(session, entity_type, entity_id, body.note)
    return {
        "item": get_item(session, entity_type, entity_id),
        "merge_id": result.merge_id,
        "batch_id": result.batch_id,
        "revision_ids": result.revision_ids,
        "skipped": result.skipped,
    }


def register(app: FastAPI) -> None:
    """Add the merge routes."""
    app.add_api_route(ENTITY + "/merge-preview", get_merge_preview, methods=["GET"])
    app.add_api_route(ENTITY + "/merge", post_merge, methods=["POST"])
    app.add_api_route(ENTITY + "/unmerge", post_unmerge, methods=["POST"])
