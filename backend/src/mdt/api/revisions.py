"""Recent changes (docs/API.md §3.4) and single revisions by ID (§3.2)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from mdt.api.deps import SessionDep
from mdt.api.schemas import RevisionIdPath
from mdt.domain.feeds import recent_changes, revision_by_id


def get_recent_changes(request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/revisions``: revisions of every type, newest first, with filters."""
    return recent_changes(session, request.query_params)


def get_revision(revision_id: RevisionIdPath, session: SessionDep) -> dict[str, Any]:
    """``GET /api/revisions/{revision_id}`` for any entity type, comments included."""
    return revision_by_id(session, revision_id)


def register(app: FastAPI) -> None:
    """Add the revision routes."""
    app.add_api_route("/api/revisions", get_recent_changes, methods=["GET"])
    app.add_api_route("/api/revisions/{revision_id}", get_revision, methods=["GET"])
