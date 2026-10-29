"""API representations of items, comments and revisions (docs/API.md §2, §3.2, §3.3).

Everything is loaded in batches: a page of items costs a fixed number of queries
(rows, document links, derived rows, virtual values, labels, snippets), whatever its
size. Functions taking rows run inside the caller's transaction; :func:`get_item` and
:func:`get_comment` open their own read transaction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from mdt.db.models import Comment, Derived, DocumentText, Revision
from mdt.db.session import read_transaction
from mdt.domain.comments import edited_comment_ids, render_markdown
from mdt.domain.derived import INITIAL
from mdt.domain.errors import NotFoundError
from mdt.domain.fieldsql import Source
from mdt.domain.labels import RefInfo, ref_infos, refs_payload
from mdt.domain.records import Row, field_meta_of, item_field_values, load_links, table_of
from mdt.domain.registry import COMMENT, ENTITY_TYPES, EntityTypeSpec, type_of_id
from mdt.domain.search import document_snippets

#: Derived columns that hold IDs; their labels go into ``refs`` as ``derived.<name>``.
DERIVED_REF_KEYS: Final = (
    "launch_event_id",
    "existed_by_event_id",
    "trajectory_event_id",
    "portfolio_entry_participation_id",
)
_CHUNK: Final = 500
_SYSTEM_KEYS: Final = ("created_at", "created_by", "updated_at", "updated_by")


def generic_spec(entity_type: str) -> EntityTypeSpec:
    """A type served by the generic ``/api/entities`` endpoints; others are 404."""
    spec = ENTITY_TYPES.get(entity_type)
    if spec is None or not spec.generic_api:
        raise NotFoundError("Unknown entity type")
    return spec


def record_spec(entity_type: str) -> EntityTypeSpec:
    """Any type with revisions (generic types and comments); others are 404."""
    spec = ENTITY_TYPES.get(entity_type)
    if spec is None:
        raise NotFoundError("Unknown entity type")
    return spec


def _chunks(ids: Sequence[str]) -> Iterable[list[str]]:
    for start in range(0, len(ids), _CHUNK):
        yield list(ids[start : start + _CHUNK])


def load_rows(session: Session, spec: EntityTypeSpec, ids: Sequence[str]) -> list[Row]:
    """Rows of ``spec`` with the given IDs, in the given order (missing IDs are skipped)."""
    table = table_of(spec)
    found: dict[str, Row] = {}
    for chunk in _chunks(list(dict.fromkeys(ids))):
        for row in session.execute(select(table).where(table.c.id.in_(chunk))).mappings():
            found[row["id"]] = dict(row)
    return [found[entity_id] for entity_id in ids if entity_id in found]


# --------------------------------------------------------------------------------------
# Derived and virtual values
# --------------------------------------------------------------------------------------


def derived_payload(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``derived`` object of an item; a missing row counts as unknown (§8.1)."""
    values: Mapping[str, Any] = row if row is not None else INITIAL.as_row()
    return {
        "launch": values["launch_value"],
        "launch_start": values["launch_start"],
        "launch_end": values["launch_end"],
        "launch_precision": values["launch_precision"],
        "launch_basis": values["launch_basis"],
        "launch_event_id": values["launch_event_id"],
        "existed_by": values["existed_by"],
        "existed_by_event_id": values["existed_by_event_id"],
        "existed_before_invasion": bool(values["existed_before_invasion"]),
        "period": values["period"],
        "period_reason": values["period_reason"],
        "war_trajectory": values["war_trajectory"],
        "trajectory_reason": values["trajectory_reason"],
        "trajectory_event_id": values["trajectory_event_id"],
        "portfolio_entry": values["portfolio_entry_value"],
        "portfolio_entry_start": values["portfolio_entry_start"],
        "portfolio_entry_end": values["portfolio_entry_end"],
        "portfolio_entry_precision": values["portfolio_entry_precision"],
        "portfolio_entry_participation_id": values["portfolio_entry_participation_id"],
        "computed_at": row["computed_at"] if row is not None else None,
    }


def derived_rows(session: Session, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Stored ``derived`` rows by entity ID."""
    table = Derived.__table__
    assert isinstance(table, Table)
    result: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(ids):
        for row in session.execute(select(table).where(table.c.entity_id.in_(chunk))).mappings():
            result[row["entity_id"]] = dict(row)
    return result


def virtual_values(
    session: Session, spec: EntityTypeSpec, ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Every per-row virtual field of the given entities, evaluated with the same
    expressions that filters and sorting use (one query per 500 IDs)."""
    source = Source(spec)
    columns = source.virtual_columns()
    result: dict[str, dict[str, Any]] = {entity_id: {} for entity_id in ids}
    if not columns:
        return result
    bools = {field.name for field in spec.fields if field.virtual and field.type == "bool"}
    statement = select(source.table.c.id, *(expr.label(name) for name, expr in columns))
    for chunk in _chunks(ids):
        rows = session.execute(statement.where(source.table.c.id.in_(chunk))).mappings()
        for row in rows:
            result[row["id"]] = {
                name: bool(row[name]) if name in bools else int(row[name] or 0)
                for name, _ in columns
            }
    return result


def open_comments_by_field(session: Session, entity_id: str) -> dict[str, int]:
    """Open root comments per field; entity-level threads under ``""``."""
    comment = Comment.__table__
    assert isinstance(comment, Table)
    rows = session.execute(
        select(func.coalesce(comment.c.field, ""), func.count())
        .where(
            comment.c.subject_id == entity_id,
            comment.c.parent_id.is_(None),
            comment.c.status == "open",
            comment.c.deleted_at.is_(None),
        )
        .group_by(func.coalesce(comment.c.field, ""))
    )
    return {str(field): int(count) for field, count in rows}


def document_text(session: Session, text_hash: str | None) -> str | None:
    """The stored text of a document's current text version, or None."""
    if not text_hash:
        return None
    return session.execute(
        select(DocumentText.text).where(DocumentText.text_hash == text_hash)
    ).scalar()


# --------------------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------------------


def _ref_ids(
    spec: EntityTypeSpec,
    row: Mapping[str, Any],
    links: Sequence[Mapping[str, Any]],
    derived: Mapping[str, Any] | None,
) -> list[str]:
    ids = [row[field.name] for field in spec.stored_fields if field.type == "ref"]
    if derived is not None:
        ids.extend(derived[key] for key in DERIVED_REF_KEYS)
    ids.extend(link["subject_id"] for link in links)
    return [entity_id for entity_id in ids if entity_id]


def _refs(
    spec: EntityTypeSpec,
    row: Mapping[str, Any],
    links: Sequence[Mapping[str, Any]],
    derived: Mapping[str, Any] | None,
    infos: Mapping[str, RefInfo],
) -> dict[str, dict[str, Any]]:
    keyed: list[tuple[str, str | None]] = [
        (field.name, row[field.name]) for field in spec.stored_fields if field.type == "ref"
    ]
    if derived is not None:
        keyed.extend((f"derived.{key}", derived[key]) for key in DERIVED_REF_KEYS)
    keyed.extend((f"links.{link['subject_id']}", link["subject_id"]) for link in links)
    return {key: infos[value].as_dict() for key, value in keyed if value and value in infos}


def serialize_items(
    session: Session,
    spec: EntityTypeSpec,
    rows: Sequence[Mapping[str, Any]],
    *,
    detail: bool = False,
    match: str | None = None,
) -> list[dict[str, Any]]:
    """Items of API §2 for stored rows, loaded in batches.

    ``detail`` adds ``virtual.open_comments_by_field`` and, for documents,
    ``fields.text``; ``match`` (an FTS expression) adds search snippets to documents.
    """
    ids = [row["id"] for row in rows]
    links = load_links(session, ids) if spec.has_field("links") else {}
    derived = derived_rows(session, ids) if spec.has_derived else {}
    virtual = virtual_values(session, spec, ids)
    snippets = document_snippets(session, ids, match) if match and spec.name == "document" else {}
    wanted = list(ids)
    for row in rows:
        derived_row = derived.get(row["id"]) if spec.has_derived else None
        wanted.extend(_ref_ids(spec, row, links.get(row["id"], []), derived_row))
    infos = ref_infos(session, wanted)

    items = []
    for row in rows:
        entity_id = row["id"]
        row_links = links.get(entity_id, [])
        derived_row = derived.get(entity_id)
        item: dict[str, Any] = {
            "id": entity_id,
            "type": spec.name,
            "label": infos[entity_id].label if entity_id in infos else entity_id,
            "version": row["version"],
            **{key: row[key] for key in _SYSTEM_KEYS},
            "deleted_at": row["deleted_at"],
            "deleted_by": row["deleted_by"],
        }
        if spec.curated:
            item["merged_into"] = row["merged_into"]
        fields = item_field_values(spec, row, row_links if spec.has_field("links") else None)
        values = dict(virtual.get(entity_id, {}))
        if detail:
            values["open_comments_by_field"] = open_comments_by_field(session, entity_id)
            if spec.name == "document":
                fields["text"] = document_text(session, row["text_hash"])
        item["fields"] = fields
        item["field_meta"] = field_meta_of(spec, row)
        if spec.has_derived:
            item["derived"] = derived_payload(derived_row)
        item["virtual"] = values
        item["refs"] = _refs(spec, row, row_links, derived_row if spec.has_derived else None, infos)
        item["search_snippet"] = snippets.get(entity_id) if spec.name == "document" else None
        items.append(item)
    return items


def item_payload(session: Session, spec: EntityTypeSpec, entity_id: str) -> dict[str, Any]:
    """The detail item of one entity (deleted ones included); 404 if it does not exist.
    Runs inside the caller's transaction."""
    rows = load_rows(session, spec, [entity_id])
    if not rows:
        raise NotFoundError()
    return serialize_items(session, spec, rows, detail=True)[0]


def get_item(session: Session, entity_type: str, entity_id: str) -> dict[str, Any]:
    """``GET /api/entities/{type}/{id}``: the detail item in its own read transaction."""
    spec = generic_spec(entity_type)
    with read_transaction(session):
        return item_payload(session, spec, entity_id)


# --------------------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------------------


def serialize_comments(session: Session, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Comment objects of API §3.3; ``body_html`` is rendered on read."""
    infos = ref_infos(session, [row["subject_id"] for row in rows])
    edited = edited_comment_ids(session, [row["id"] for row in rows])
    result = []
    for row in rows:
        subject_id = row["subject_id"]
        result.append(
            {
                "id": row["id"],
                "subject_id": subject_id,
                "subject_type": type_of_id(subject_id),
                "subject_label": infos[subject_id].label if subject_id in infos else subject_id,
                "field": row["field"],
                "parent_id": row["parent_id"],
                "body_md": row["body_md"],
                "body_html": render_markdown(row["body_md"]),
                "status": row["status"],
                "resolved_by": row["resolved_by"],
                "resolved_at": row["resolved_at"],
                **{key: row[key] for key in _SYSTEM_KEYS},
                "version": row["version"],
                "edited": row["id"] in edited,
                "deleted_at": row["deleted_at"],
                "deleted_by": row["deleted_by"],
            }
        )
    return result


def comment_payload(session: Session, comment_id: str) -> dict[str, Any]:
    """One comment object inside the caller's transaction; 404 if missing."""
    rows = load_rows(session, COMMENT, [comment_id])
    if not rows:
        raise NotFoundError()
    return serialize_comments(session, rows)[0]


def get_comment(session: Session, comment_id: str) -> dict[str, Any]:
    """``GET /api/comments/{id}`` in its own read transaction."""
    with read_transaction(session):
        return comment_payload(session, comment_id)


# --------------------------------------------------------------------------------------
# Revisions
# --------------------------------------------------------------------------------------


def field_ref_ids(spec: EntityTypeSpec, fields: Mapping[str, Any] | None) -> list[str]:
    """IDs referenced by the ``ref`` and ``doc_links`` values of a ``fields`` object."""
    ids: list[str] = []
    for name, value in (fields or {}).items():
        if not spec.has_field(name):
            continue
        kind = spec.field(name).type
        if kind == "ref" and isinstance(value, str):
            ids.append(value)
        elif kind == "doc_links" and isinstance(value, list):
            ids.extend(
                link["subject_id"]
                for link in value
                if isinstance(link, dict) and isinstance(link.get("subject_id"), str)
            )
    return ids


def diff_ref_ids(spec: EntityTypeSpec, diff: Mapping[str, Any] | None) -> list[str]:
    """IDs referenced by the old and new values of a diff's ``fields`` section."""
    changes = (diff or {}).get("fields") or {}
    ids: list[str] = []
    for side in (0, 1):
        ids.extend(
            field_ref_ids(
                spec,
                {
                    name: pair[side]
                    for name, pair in changes.items()
                    if isinstance(pair, list) and len(pair) == 2
                },
            )
        )
    return ids


def revision_refs(
    session: Session, spec: EntityTypeSpec, revisions: Iterable[Revision], *, snapshots: bool
) -> dict[str, dict[str, Any]]:
    """``refs`` (keyed by ID) for the IDs in the revisions' diffs and, with
    ``snapshots``, in their snapshots."""
    ids: list[str] = []
    for revision in revisions:
        ids.extend(diff_ref_ids(spec, revision.diff))
        if snapshots:
            ids.extend(field_ref_ids(spec, (revision.snapshot or {}).get("fields")))
    return refs_payload(session, ids)
