"""Comments (docs/DATA_MODEL.md §6.6, docs/API.md §3.3).

Comments go through the same write path as entities (``entity_type = comment``); every
change creates a revision. ``body_html`` is rendered on read by :func:`render_markdown`
and never stored.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from markdown_it import MarkdownIt
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import Revision
from mdt.db.session import write_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import Problems, ValidationError
from mdt.domain.records import load_row
from mdt.domain.registry import COMMENT, ENTITY_TYPES, type_of_id
from mdt.domain.revisions import restore_version, soft_delete, undelete
from mdt.domain.writes import (
    ChangeResult,
    WriteUnit,
    clean_note,
    create_record,
    ensure_live,
    normalize_changes,
    require_row,
    snapshot_of,
    update_record,
)

# --------------------------------------------------------------------------------------
# Markdown rendering (API §3.3)
# --------------------------------------------------------------------------------------

#: CommonMark with tables, strikethrough and bare links; raw HTML is not rendered.
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
    ["linkify", "table", "strikethrough"]
)


def render_markdown(body_md: str) -> str:
    """Render a comment body to HTML, computed on read (API §3.3)."""
    return str(_MARKDOWN.render(body_md))


# --------------------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------------------


def _check_body(unit: WriteUnit, provided: Mapping[str, Any]) -> None:
    body = provided.get("body_md")
    limit = unit.settings.max_comment_chars
    if isinstance(body, str) and len(body) > limit:
        raise ValidationError.single("body_md", f"must be at most {limit} characters")


def _thread_values(unit: WriteUnit, provided: dict[str, Any]) -> dict[str, Any]:
    """Validate subject, field and parent; return the values set by the domain layer."""
    problems = Problems()
    subject_id = provided.get("subject_id")
    subject_type = type_of_id(subject_id) if subject_id else None
    if subject_type == "comment":
        problems.add("subject_id", "Comments cannot be the subject of a comment")
    field_name = provided.get("field")
    if field_name and subject_type in ENTITY_TYPES:
        subject_spec = ENTITY_TYPES[subject_type]
        if not subject_spec.has_field(field_name) or subject_spec.field(field_name).internal:
            problems.add("field", "is not a field of the subject's entity type")
    extra: dict[str, Any] = {"status": "open"}
    parent_id = provided.get("parent_id")
    if parent_id:
        parent = load_row(unit.session, COMMENT, parent_id)
        if parent is None:
            problems.add("parent_id", "refers to a comment that does not exist")
        elif parent["parent_id"] is not None:
            problems.add("parent_id", "Replies must answer a root comment")
        elif parent["subject_id"] != subject_id:
            problems.add("parent_id", "The root comment belongs to another subject")
        elif parent["deleted_at"] is not None:
            problems.add("parent_id", "A deleted thread cannot be answered")
        elif field_name and field_name != parent["field"]:
            problems.add("field", "A reply belongs to the field of its root comment")
        else:
            extra = {"status": None, "field": parent["field"]}
    problems.raise_if_any()
    return extra


def create_comment_from_changes(
    session: Session, changes: Mapping[str, Any], actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Create a comment from ``{subject_id, field, parent_id, body_md}``.

    Roots start ``open``; replies have status null and the field of their root.
    """
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        provided = normalize_changes(unit, changes, creating=True)
        _check_body(unit, provided)
        extra = _thread_values(unit, provided)
        if "field" in extra:
            provided.pop("field", None)
        return create_record(unit, provided, note=clean, batch_id=None, extra_values=extra)


def create_comment(
    session: Session,
    subject_id: str,
    body_md: str,
    actor: Actor,
    *,
    field: str | None = None,
    parent_id: str | None = None,
) -> ChangeResult:
    """Create a root comment or a reply."""
    return create_comment_from_changes(
        session,
        {"subject_id": subject_id, "field": field, "parent_id": parent_id, "body_md": body_md},
        actor,
    )


def edit_comment_from_changes(
    session: Session,
    comment_id: str,
    changes: Mapping[str, Any],
    actor: Actor,
    *,
    note: str | None = None,
) -> ChangeResult:
    """Change a comment's body (the only editable field)."""
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        row = require_row(unit, comment_id)
        ensure_live(row)
        provided = normalize_changes(unit, changes, creating=False)
        _check_body(unit, provided)
        return update_record(unit, row, provided, note=clean, batch_id=None)


def edit_comment(
    session: Session, comment_id: str, body_md: str, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Edit a comment's Markdown body."""
    return edit_comment_from_changes(session, comment_id, {"body_md": body_md}, actor, note=note)


def _set_status(
    session: Session, comment_id: str, actor: Actor, status: str, note: str | None
) -> ChangeResult:
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        row = require_row(unit, comment_id)
        if row["parent_id"] is not None:
            raise ValidationError.single("status", "Only root comments can be resolved or reopened")
        ensure_live(row)
        if row["status"] == status:
            # Idempotent: no revision (DATA_MODEL §6.6).
            return ChangeResult(
                "comment",
                comment_id,
                False,
                int(row["version"]),
                None,
                snapshot_of(COMMENT, row, None),
            )
        resolved = status == "resolved"
        values = normalize_changes(
            unit,
            {
                "status": status,
                "resolved_by": actor.by if resolved else None,
                "resolved_at": unit.ts if resolved else None,
            },
            creating=False,
            allow_system=True,
        )
        return update_record(
            unit,
            row,
            values,
            note=clean,
            batch_id=None,
            action="resolve" if resolved else "reopen",
        )


def resolve_comment(
    session: Session, comment_id: str, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Resolve a root comment (idempotent)."""
    return _set_status(session, comment_id, actor, "resolved", note)


def reopen_comment(
    session: Session, comment_id: str, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Reopen a resolved root comment (idempotent)."""
    return _set_status(session, comment_id, actor, "open", note)


def delete_comment(
    session: Session, comment_id: str, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Soft-delete a comment; deleting a root hides its thread (replies are unchanged)."""
    return soft_delete(session, "comment", comment_id, actor, note=note)


def undelete_comment(
    session: Session, comment_id: str, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Undelete a comment."""
    return undelete(session, "comment", comment_id, actor, note=note)


def restore_comment(
    session: Session, comment_id: str, version: int, actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Restore a comment's body from an old version."""
    return restore_version(session, "comment", comment_id, version, actor, note=note)


# --------------------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------------------


def edited_comment_ids(session: Session, comment_ids: Iterable[str]) -> set[str]:
    """IDs of comments whose body changed in any revision after version 1."""
    ids = list(dict.fromkeys(comment_ids))
    if not ids:
        return set()
    edited: set[str] = set()
    for start in range(0, len(ids), 500):
        rows = session.execute(
            select(Revision.entity_id, Revision.diff).where(
                Revision.entity_id.in_(ids[start : start + 500]), Revision.version > 1
            )
        )
        for entity_id, diff in rows:
            if "body_md" in ((diff or {}).get("fields") or {}):
                edited.add(entity_id)
    return edited
