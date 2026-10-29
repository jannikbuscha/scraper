"""Generic entity endpoints (docs/API.md §3.2): lists, facets, exports, detail, writes,
histories, diffs, restore and bulk edit for every type with ``generic_api``. Comments
have their own endpoints (:mod:`mdt.api.comments`), so ``comment`` is 404 here."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from starlette.responses import Response

from mdt.api.deps import RestoreActor, SessionDep, UiActor
from mdt.api.exports import export_response
from mdt.api.schemas import (
    BulkBody,
    CreateBody,
    FromVersion,
    PatchBody,
    RestoreBody,
    StateChangeBody,
    ToVersion,
    VerifyFieldBody,
    VersionPath,
)
from mdt.domain.feeds import entity_diff, entity_revision, entity_revisions
from mdt.domain.query import facet_values, list_entities
from mdt.domain.revisions import (
    apply_change,
    bulk_apply,
    restore_version,
    set_field_verification,
    soft_delete,
    undelete,
)
from mdt.domain.serialize import generic_spec, get_item

ENTITIES = "/api/entities/{entity_type}"
ENTITY = ENTITIES + "/{entity_id}"


def get_entities(entity_type: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/entities/{type}``: one page of items (query grammar of API §4)."""
    return list_entities(session, entity_type, request.query_params)


def get_facets(entity_type: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/entities/{type}/facets?field=…``: value counts under the other filters."""
    return facet_values(session, entity_type, request.query_params)


def get_export(entity_type: str, request: Request, session: SessionDep) -> Response:
    """``GET /api/entities/{type}/export?format=csv|xlsx``: every matching row."""
    return export_response(session, entity_type, request.query_params)


def create_entity(
    entity_type: str, body: CreateBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/entities/{type}`` → ``201 {item, revision_id, warnings}``."""
    generic_spec(entity_type)
    result = apply_change(session, entity_type, None, body.data, actor, note=body.note)
    return {
        "item": get_item(session, entity_type, result.entity_id),
        "revision_id": result.revision_id,
        "warnings": result.warnings_payload(),
    }


def get_entity(entity_type: str, entity_id: str, session: SessionDep) -> dict[str, Any]:
    """``GET /api/entities/{type}/{id}``: the detail item (deleted items too)."""
    return {"item": get_item(session, entity_type, entity_id)}


def patch_entity(
    entity_type: str, entity_id: str, body: PatchBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``PATCH /api/entities/{type}/{id}``; a no-op returns ``changed: false``."""
    generic_spec(entity_type)
    result = apply_change(
        session,
        entity_type,
        entity_id,
        body.changes,
        actor,
        note=body.note,
        expected_version=body.expected_version,
    )
    return {
        "item": get_item(session, entity_type, entity_id),
        "changed": result.changed,
        "revision_id": result.revision_id,
        "warnings": result.warnings_payload(),
    }


def delete_entity(
    entity_type: str, entity_id: str, body: StateChangeBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST …/{id}/delete`` (soft delete; ``cascade`` also deletes dependent services)."""
    generic_spec(entity_type)
    result = soft_delete(
        session,
        entity_type,
        entity_id,
        actor,
        note=body.note,
        expected_version=body.expected_version,
        cascade=body.cascade,
    )
    return {
        "item": get_item(session, entity_type, entity_id),
        "revision_id": result.revision_id,
        "batch_id": result.batch_id,
    }


def undelete_entity(
    entity_type: str, entity_id: str, body: StateChangeBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST …/{id}/undelete`` (``cascade`` also undeletes the rows of the delete batch)."""
    generic_spec(entity_type)
    result = undelete(
        session,
        entity_type,
        entity_id,
        actor,
        note=body.note,
        expected_version=body.expected_version,
        cascade=body.cascade,
    )
    return {
        "item": get_item(session, entity_type, entity_id),
        "revision_id": result.revision_id,
        "batch_id": result.batch_id,
    }


def verify_field(
    entity_type: str, entity_id: str, body: VerifyFieldBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST …/{id}/verify-field``; setting the current status again writes nothing
    (``revision_id: null``)."""
    generic_spec(entity_type)
    result = set_field_verification(
        session,
        entity_type,
        entity_id,
        body.field,
        body.status,
        actor,
        note=body.note,
        evidence_id=body.evidence_id,
        expected_version=body.expected_version,
    )
    return {"item": get_item(session, entity_type, entity_id), "revision_id": result.revision_id}


def get_revisions(
    entity_type: str, entity_id: str, request: Request, session: SessionDep
) -> dict[str, Any]:
    """``GET …/{id}/revisions``: RevisionSummary list, newest first."""
    generic_spec(entity_type)
    return entity_revisions(session, entity_type, entity_id, request.query_params)


def get_revision(
    entity_type: str, entity_id: str, version: VersionPath, session: SessionDep
) -> dict[str, Any]:
    """``GET …/{id}/revisions/{version}``: one RevisionFull."""
    generic_spec(entity_type)
    return entity_revision(session, entity_type, entity_id, version)


def get_diff(
    entity_type: str,
    entity_id: str,
    session: SessionDep,
    from_version: FromVersion,
    to_version: ToVersion,
) -> dict[str, Any]:
    """``GET …/{id}/diff?from=&to=``: the diff between two versions (``from=0`` is the
    empty state before creation)."""
    generic_spec(entity_type)
    return entity_diff(session, entity_type, entity_id, from_version, to_version)


def restore_entity(
    entity_type: str, entity_id: str, body: RestoreBody, session: SessionDep, actor: RestoreActor
) -> dict[str, Any]:
    """``POST …/{id}/restore`` on channel ``restore``; ``dry_run`` only computes
    ``changes``."""
    generic_spec(entity_type)
    result = restore_version(
        session,
        entity_type,
        entity_id,
        body.version,
        actor,
        note=body.note,
        expected_version=body.expected_version,
        fields=body.fields,
        dry_run=body.dry_run,
    )
    return {
        "item": get_item(session, entity_type, entity_id),
        "changed": result.changed,
        "revision_id": result.revision_id,
        "warnings": result.warnings_payload(),
        "skipped_fields": result.skipped_fields,
        "changes": result.changes,
    }


def bulk_edit(
    entity_type: str, body: BulkBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/entities/{type}/bulk``: one write unit per item, shared ``batch_id``."""
    generic_spec(entity_type)
    result = bulk_apply(
        session,
        entity_type,
        body.items,
        actor,
        set_values=body.set_,
        add=body.add,
        remove=body.remove,
        note=body.note,
    )
    return {"batch_id": result.batch_id, "results": [item.as_dict() for item in result.results]}


def register(app: FastAPI) -> None:
    """Add the generic entity routes (fixed sub-paths before ``{entity_id}``)."""
    app.add_api_route(ENTITIES, get_entities, methods=["GET"])
    app.add_api_route(ENTITIES, create_entity, methods=["POST"], status_code=201)
    app.add_api_route(ENTITIES + "/facets", get_facets, methods=["GET"])
    app.add_api_route(ENTITIES + "/export", get_export, methods=["GET"])
    app.add_api_route(ENTITIES + "/bulk", bulk_edit, methods=["POST"])
    app.add_api_route(ENTITY, get_entity, methods=["GET"])
    app.add_api_route(ENTITY, patch_entity, methods=["PATCH"])
    app.add_api_route(ENTITY + "/delete", delete_entity, methods=["POST"])
    app.add_api_route(ENTITY + "/undelete", undelete_entity, methods=["POST"])
    app.add_api_route(ENTITY + "/verify-field", verify_field, methods=["POST"])
    app.add_api_route(ENTITY + "/restore", restore_entity, methods=["POST"])
    app.add_api_route(ENTITY + "/revisions", get_revisions, methods=["GET"])
    app.add_api_route(ENTITY + "/revisions/{version}", get_revision, methods=["GET"])
    app.add_api_route(ENTITY + "/diff", get_diff, methods=["GET"])
