"""Comment endpoints (docs/API.md §3.3): threads and the comment feed, create, edit,
resolve/reopen, delete/undelete, restore and the comment's history."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from mdt.api.deps import RestoreActor, SessionDep, UiActor
from mdt.api.schemas import (
    CommentCreateBody,
    CommentEditBody,
    CommentNoteBody,
    CommentRestoreBody,
    CommentVersionBody,
    FromVersion,
    ToVersion,
    VersionPath,
)
from mdt.domain.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    reopen_comment,
    resolve_comment,
    restore_comment,
    undelete_comment,
)
from mdt.domain.feeds import comments_listing, entity_diff, entity_revision, entity_revisions
from mdt.domain.serialize import get_comment

COMMENTS = "/api/comments"
COMMENT = COMMENTS + "/{comment_id}"


def get_comments(request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/comments``: the threads of ``subject_id``, or the feed without it."""
    return comments_listing(session, request.query_params)


def get_one_comment(comment_id: str, session: SessionDep) -> dict[str, Any]:
    """``GET /api/comments/{id}``."""
    return {"comment": get_comment(session, comment_id)}


def post_comment(body: CommentCreateBody, session: SessionDep, actor: UiActor) -> dict[str, Any]:
    """``POST /api/comments`` → ``201 {comment}``; roots start ``open``."""
    result = create_comment(
        session, body.subject_id, body.body_md, actor, field=body.field, parent_id=body.parent_id
    )
    return {"comment": get_comment(session, result.entity_id)}


def patch_comment(
    comment_id: str, body: CommentEditBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``PATCH /api/comments/{id}``: edit the Markdown body."""
    edit_comment(
        session,
        comment_id,
        body.body_md,
        actor,
        expected_version=body.expected_version,
        note=body.note,
    )
    return {"comment": get_comment(session, comment_id)}


def resolve(
    comment_id: str, body: CommentVersionBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/comments/{id}/resolve`` (roots only; idempotent)."""
    result = resolve_comment(session, comment_id, actor, expected_version=body.expected_version)
    return {"comment": get_comment(session, comment_id), "changed": result.changed}


def reopen(
    comment_id: str, body: CommentVersionBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/comments/{id}/reopen`` (roots only; idempotent)."""
    result = reopen_comment(session, comment_id, actor, expected_version=body.expected_version)
    return {"comment": get_comment(session, comment_id), "changed": result.changed}


def delete(
    comment_id: str, body: CommentNoteBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/comments/{id}/delete``; deleting a root hides its thread."""
    delete_comment(
        session, comment_id, actor, expected_version=body.expected_version, note=body.note
    )
    return {"comment": get_comment(session, comment_id)}


def undelete(
    comment_id: str, body: CommentNoteBody, session: SessionDep, actor: UiActor
) -> dict[str, Any]:
    """``POST /api/comments/{id}/undelete``."""
    undelete_comment(
        session, comment_id, actor, expected_version=body.expected_version, note=body.note
    )
    return {"comment": get_comment(session, comment_id)}


def restore(
    comment_id: str, body: CommentRestoreBody, session: SessionDep, actor: RestoreActor
) -> dict[str, Any]:
    """``POST /api/comments/{id}/restore``: restore the body of an old version."""
    restore_comment(
        session,
        comment_id,
        body.version,
        actor,
        expected_version=body.expected_version,
        note=body.note,
    )
    return {"comment": get_comment(session, comment_id)}


def get_revisions(comment_id: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/comments/{id}/revisions``."""
    return entity_revisions(session, "comment", comment_id, request.query_params)


def get_revision(comment_id: str, version: VersionPath, session: SessionDep) -> dict[str, Any]:
    """``GET /api/comments/{id}/revisions/{version}``."""
    return entity_revision(session, "comment", comment_id, version)


def get_diff(
    comment_id: str,
    session: SessionDep,
    from_version: FromVersion,
    to_version: ToVersion,
) -> dict[str, Any]:
    """``GET /api/comments/{id}/diff?from=&to=``."""
    return entity_diff(session, "comment", comment_id, from_version, to_version)


def register(app: FastAPI) -> None:
    """Add the comment routes."""
    app.add_api_route(COMMENTS, get_comments, methods=["GET"])
    app.add_api_route(COMMENTS, post_comment, methods=["POST"], status_code=201)
    app.add_api_route(COMMENT, get_one_comment, methods=["GET"])
    app.add_api_route(COMMENT, patch_comment, methods=["PATCH"])
    app.add_api_route(COMMENT + "/resolve", resolve, methods=["POST"])
    app.add_api_route(COMMENT + "/reopen", reopen, methods=["POST"])
    app.add_api_route(COMMENT + "/delete", delete, methods=["POST"])
    app.add_api_route(COMMENT + "/undelete", undelete, methods=["POST"])
    app.add_api_route(COMMENT + "/restore", restore, methods=["POST"])
    app.add_api_route(COMMENT + "/revisions", get_revisions, methods=["GET"])
    app.add_api_route(COMMENT + "/revisions/{version}", get_revision, methods=["GET"])
    app.add_api_route(COMMENT + "/diff", get_diff, methods=["GET"])
