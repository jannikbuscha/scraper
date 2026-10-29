"""Request shapes (docs/API.md §3.2, §3.3): the bodies of the write endpoints and the
typed path and query parameters.

The models check the shape of a request (keys and JSON types; unknown keys are refused);
the domain functions validate the values themselves (field names, codes, references,
lengths). Integers and booleans are strict: ``"3"`` or ``1.0`` is not a version and
``1`` is not ``true``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool

#: A record version in a request body.
Version = Annotated[int, Field(strict=True, ge=0)]
#: ``…/revisions/{version}``.
VersionPath = Annotated[int, Path(ge=0)]
#: ``/api/revisions/{revision_id}``.
RevisionIdPath = Annotated[int, Path(ge=1)]
#: ``…/diff?from=`` (0 = the empty state before creation) and ``…&to=``.
FromVersion = Annotated[int, Query(alias="from", ge=0)]
ToVersion = Annotated[int, Query(alias="to", ge=0)]


class Body(BaseModel):
    """Base of every request body: unknown keys are a validation error."""

    model_config = ConfigDict(extra="forbid")


class CreateBody(Body):
    """``POST /api/entities/{type}``."""

    data: dict[str, Any]
    note: str | None = None


class PatchBody(Body):
    """``PATCH /api/entities/{type}/{id}``."""

    changes: dict[str, Any]
    note: str | None = None


class StateChangeBody(Body):
    """``POST …/{id}/delete`` and ``…/{id}/undelete``."""

    note: str | None = None
    cascade: StrictBool = False


class VerifyFieldBody(Body):
    """``POST …/{id}/verify-field``."""

    field: str
    status: str
    evidence_id: str | None = None
    note: str | None = None


class RestoreBody(Body):
    """``POST …/{id}/restore``; ``fields`` null restores every restorable field."""

    version: Version
    fields: list[str] | None = None
    dry_run: StrictBool = False
    note: str | None = None


class BulkBody(Body):
    """``POST /api/entities/{type}/bulk``; the operations are validated by the domain."""

    ids: list[str]
    set_: dict[str, Any] = Field(default_factory=dict, alias="set")
    add: dict[str, Any] = Field(default_factory=dict)
    remove: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class CommentCreateBody(Body):
    """``POST /api/comments``."""

    subject_id: str
    field: str | None = None
    parent_id: str | None = None
    body_md: str


class CommentEditBody(Body):
    """``PATCH /api/comments/{id}``."""

    body_md: str
    note: str | None = None


class CommentStatusBody(Body):
    """``POST /api/comments/{id}/resolve`` and ``…/reopen``: an empty object."""


class CommentNoteBody(Body):
    """``POST /api/comments/{id}/delete`` and ``…/undelete``."""

    note: str | None = None


class CommentRestoreBody(Body):
    """``POST /api/comments/{id}/restore``."""

    version: Version
    note: str | None = None
