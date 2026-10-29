"""Request shapes (docs/API.md §3.2, §3.3): the bodies of the write endpoints and the
typed path and query parameters.

The models check the shape of a request (keys and JSON types; unknown keys are refused);
the domain functions validate the values themselves (field names, codes, references,
lengths). Integers and booleans are strict: ``"3"`` or ``1.0`` is not a version and
``1`` is not ``true``. Versions and revision IDs must fit SQLite's 64-bit integers.

Before any of that, every string and object key of a body must be valid Unicode text:
JSON can encode unpaired UTF-16 surrogates (``"\\ud800"``), which are not characters and
cannot be stored. Such a body is a ``400 validation_error`` with the dotted path of each
bad value (API §1.2), whatever field or parameter the string was meant for.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from mdt.domain.errors import ValidationError
from mdt.domain.normalize import unpaired_surrogate_problems

MAX_SQL_INT: Final = 2**63 - 1

#: A record version in a request body.
Version = Annotated[int, Field(strict=True, ge=0, le=MAX_SQL_INT)]
#: ``…/revisions/{version}``.
VersionPath = Annotated[int, Path(ge=0, le=MAX_SQL_INT)]
#: ``/api/revisions/{revision_id}``.
RevisionIdPath = Annotated[int, Path(ge=1, le=MAX_SQL_INT)]
#: ``…/diff?from=`` (0 = the empty state before creation) and ``…&to=``.
FromVersion = Annotated[int, Query(alias="from", ge=0, le=MAX_SQL_INT)]
ToVersion = Annotated[int, Query(alias="to", ge=0, le=MAX_SQL_INT)]


class Body(BaseModel):
    """Base of every request body: unknown keys are a validation error, and so is text
    that is not valid Unicode (checked first, on the parsed JSON)."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _valid_unicode(cls, data: Any) -> Any:
        # A domain ValidationError is not one of Pydantic's error types, so it leaves
        # validation unchanged and reaches the error handler with its field paths.
        problems = unpaired_surrogate_problems(data)
        if problems:
            raise ValidationError(problems)
        return data


class CreateBody(Body):
    """``POST /api/entities/{type}``."""

    data: dict[str, Any]
    note: str | None = None


class PatchBody(Body):
    """``PATCH /api/entities/{type}/{id}``."""

    expected_version: Version
    changes: dict[str, Any]
    note: str | None = None


class StateChangeBody(Body):
    """``POST …/{id}/delete`` and ``…/{id}/undelete``."""

    expected_version: Version
    note: str | None = None
    cascade: StrictBool = False


class VerifyFieldBody(Body):
    """``POST …/{id}/verify-field``."""

    expected_version: Version
    field: str
    status: str
    evidence_id: str | None = None
    note: str | None = None


class RestoreBody(Body):
    """``POST …/{id}/restore``; ``fields`` null restores every restorable field."""

    expected_version: Version
    version: Version
    fields: list[str] | None = None
    dry_run: StrictBool = False
    note: str | None = None


class BulkBody(Body):
    """``POST /api/entities/{type}/bulk``; the items are validated by the domain."""

    items: list[Any]
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

    expected_version: Version
    body_md: str
    note: str | None = None


class CommentVersionBody(Body):
    """``POST /api/comments/{id}/resolve`` and ``…/reopen``."""

    expected_version: Version


class CommentNoteBody(Body):
    """``POST /api/comments/{id}/delete`` and ``…/undelete``."""

    expected_version: Version
    note: str | None = None


class CommentRestoreBody(Body):
    """``POST /api/comments/{id}/restore``."""

    expected_version: Version
    version: Version
    note: str | None = None
