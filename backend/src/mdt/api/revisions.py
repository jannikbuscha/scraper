"""Recent changes (docs/API.md §3.4) and single revisions by ID (§3.2)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from mdt.api.deps import SessionDep
from mdt.api.schemas import RevisionIdPath
from mdt.domain.feeds import recent_changes, revision_authors, revision_by_id


def get_recent_changes(request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/revisions``: revisions of every type, newest first, with filters."""
    return recent_changes(session, request.query_params)


def get_authors(session: SessionDep) -> dict[str, Any]:
    """``GET /api/revisions/authors``: every author that wrote a revision."""
    return revision_authors(session)


def get_revision(revision_id: RevisionIdPath, session: SessionDep) -> dict[str, Any]:
    """``GET /api/revisions/{revision_id}`` for any entity type, comments included."""
    return revision_by_id(session, revision_id)


def register(app: FastAPI) -> None:
    """Add the revision routes (``authors`` before ``{revision_id}``)."""
    app.add_api_route("/api/revisions", get_recent_changes, methods=["GET"])
    app.add_api_route("/api/revisions/authors", get_authors, methods=["GET"])
    app.add_api_route("/api/revisions/{revision_id}", get_revision, methods=["GET"])
