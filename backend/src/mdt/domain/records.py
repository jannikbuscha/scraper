"""Conversion between stored rows and API values (docs/DATA_MODEL.md §1, §2.1, §6.3).

Rows are read and written through SQLAlchemy Core (``Model.__table__``); a row is a
plain mapping of column names to values. Partial dates are rebuilt from their three
columns, document links come from ``document_link``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from mdt.db.models import ENTITY_MODELS, DocumentLink
from mdt.domain.dates import parse_partial_date, partial_date_from_columns
from mdt.domain.registry import EntityTypeSpec, FieldSpec

Row = dict[str, Any]


def table_of(spec: EntityTypeSpec) -> Table:
    """The Core table of an entity type."""
    table = ENTITY_MODELS[spec.name].__table__
    assert isinstance(table, Table)
    return table


def load_row(session: Session, spec: EntityTypeSpec, entity_id: str) -> Row | None:
    """Read one row as a dict (None if missing), inside the current transaction."""
    table = table_of(spec)
    row = session.execute(select(table).where(table.c.id == entity_id)).mappings().first()
    return dict(row) if row is not None else None


def load_links(session: Session, document_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """API representation of the links of each document (sorted by subject ID)."""
    ids = list(dict.fromkeys(document_ids))
    result: dict[str, list[dict[str, Any]]] = {doc_id: [] for doc_id in ids}
    if not ids:
        return result
    rows = session.scalars(
        select(DocumentLink)
        .where(DocumentLink.document_id.in_(ids))
        .order_by(DocumentLink.document_id, DocumentLink.subject_id)
    )
    for link in rows:
        result[link.document_id].append(link_to_api(link))
    return result


def link_to_api(link: DocumentLink) -> dict[str, Any]:
    """One document link in API representation."""
    return {
        "subject_id": link.subject_id,
        "origin": link.origin,
        "state": link.state,
        "matched_aliases": list(link.matched_aliases or []),
        "match_count": link.match_count,
        "snippet": link.snippet,
    }


def api_value(
    spec: FieldSpec, row: Mapping[str, Any], links: list[dict[str, Any]] | None = None
) -> Any:
    """The API value of a stored field."""
    if spec.type == "partial_date":
        name = spec.name
        return partial_date_from_columns(
            row[f"{name}_start"], row[f"{name}_end"], row[f"{name}_precision"]
        )
    if spec.type == "doc_links":
        return copy.deepcopy(links or [])
    value = row[spec.name]
    if spec.is_list:
        return copy.deepcopy(list(value)) if value else []
    if value is None:
        return None
    if spec.type == "bool":
        return bool(value)
    if spec.type == "number":
        return float(value)
    if spec.type == "json":
        return copy.deepcopy(value)
    return value


def tracked_values(
    spec: EntityTypeSpec, row: Mapping[str, Any], links: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Every tracked field in API representation (the ``fields`` of a snapshot)."""
    return {field.name: api_value(field, row, links) for field in spec.tracked_fields}


def stored_values(
    spec: EntityTypeSpec, row: Mapping[str, Any], links: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Every stored field (tracked or not, system columns excluded) in API representation."""
    return {field.name: api_value(field, row, links) for field in spec.stored_fields}


def item_field_values(
    spec: EntityTypeSpec, row: Mapping[str, Any], links: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The ``fields`` object of an API item: every stored field except system columns
    and internal fields (API §2)."""
    return {field.name: api_value(field, row, links) for field in spec.api_fields}


def state_of(spec: EntityTypeSpec, row: Mapping[str, Any]) -> dict[str, Any]:
    """The ``state`` of a snapshot: deletion (and merge for curated entities)."""
    state = {"deleted_at": row["deleted_at"], "deleted_by": row["deleted_by"]}
    if spec.curated:
        state["merged_into"] = row["merged_into"]
    return state


def field_meta_of(spec: EntityTypeSpec, row: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of the row's ``field_meta`` (comments have none)."""
    if not spec.curated:
        return {}
    return copy.deepcopy(dict(row.get("field_meta") or {}))


def to_columns(spec: FieldSpec, value: Any) -> dict[str, Any]:
    """Column values for a normalised API value of a stored field (document links live
    in ``document_link`` and have no column)."""
    if spec.type == "doc_links":
        return {}
    if spec.type == "partial_date":
        name = spec.name
        if value is None:
            return {f"{name}_start": None, f"{name}_end": None, f"{name}_precision": None}
        parsed = parse_partial_date(value)
        return {
            f"{name}_start": parsed.start_iso,
            f"{name}_end": parsed.end_iso,
            f"{name}_precision": parsed.precision,
        }
    if spec.is_list:
        return {spec.name: copy.deepcopy(value) if value else []}
    if spec.type == "json":
        return {spec.name: copy.deepcopy(value)}
    return {spec.name: value}
