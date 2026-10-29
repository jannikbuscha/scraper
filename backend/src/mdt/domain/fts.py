"""Full-text search maintenance and query building (docs/DATA_MODEL.md §10).

Every entity has a stable integer key in ``search_key``; ``fts_entity(body)`` and
``fts_document(title, body)`` use it as their rowid. FTS rows are kept for soft-deleted
entities, so the trash stays searchable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from mdt.db.models import DocumentText, SearchKey
from mdt.domain.errors import ValidationError
from mdt.domain.records import load_links, stored_values, table_of
from mdt.domain.registry import ENTITY_TYPES, FTS_TYPES, EntityTypeSpec
from mdt.domain.text import normalize_for_search

MAX_QUERY_CHARS = 200
MAX_QUERY_TOKENS = 16

_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')


def entity_body(spec: EntityTypeSpec, values: Mapping[str, Any]) -> str:
    """The ``fts_entity`` body: normalised string, text, slug, string-list and URL-list
    values of the tracked fields plus alias texts (never a document's full text)."""
    parts: list[str] = []
    for field in spec.tracked_fields:
        value = values.get(field.name)
        if value is None:
            continue
        if field.type in FTS_TYPES:
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
            else:
                parts.append(str(value))
        elif field.type == "alias_list":
            parts.extend(alias["text"] for alias in value)
    return normalize_for_search("\n".join(parts))


def document_title(values: Mapping[str, Any]) -> str:
    """The ``fts_document.title`` column: title and English title."""
    return normalize_for_search(
        "\n".join(str(values[name]) for name in ("title", "title_en") if values.get(name))
    )


def search_rowid(session: Session, entity_id: str, entity_type: str) -> int:
    """The stable FTS rowid of an entity (created on first use)."""
    rowid = session.execute(
        select(SearchKey.rowid).where(SearchKey.entity_id == entity_id)
    ).scalar()
    if rowid is not None:
        return int(rowid)
    result = session.execute(
        insert(SearchKey)
        .values(entity_id=entity_id, entity_type=entity_type)
        .returning(SearchKey.rowid)
    )
    return int(result.scalar_one())


def document_text(session: Session, text_hash: str | None) -> str:
    """The stored text of a text version ('' if none)."""
    if not text_hash:
        return ""
    value = session.execute(
        select(DocumentText.text).where(DocumentText.text_hash == text_hash)
    ).scalar()
    return str(value) if value is not None else ""


def index_entity(
    session: Session, spec: EntityTypeSpec, entity_id: str, values: Mapping[str, Any]
) -> None:
    """Insert or replace the FTS rows of an entity (``values``: its stored API values)."""
    rowid = search_rowid(session, entity_id, spec.name)
    session.execute(
        text("INSERT OR REPLACE INTO fts_entity(rowid, body) VALUES (:rowid, :body)"),
        {"rowid": rowid, "body": entity_body(spec, values)},
    )
    if spec.name == "document":
        session.execute(
            text(
                "INSERT OR REPLACE INTO fts_document(rowid, title, body) "
                "VALUES (:rowid, :title, :body)"
            ),
            {
                "rowid": rowid,
                "title": document_title(values),
                "body": normalize_for_search(document_text(session, values.get("text_hash"))),
            },
        )


def reindex_all(session: Session) -> int:
    """Rebuild both FTS tables from the entity tables (``mdt reindex``)."""
    session.execute(text("DELETE FROM fts_entity"))
    session.execute(text("DELETE FROM fts_document"))
    count = 0
    for spec in ENTITY_TYPES.values():
        table = table_of(spec)
        rows = [dict(row) for row in session.execute(select(table)).mappings()]
        links = load_links(session, [row["id"] for row in rows]) if spec.name == "document" else {}
        for row in rows:
            index_entity(session, spec, row["id"], stored_values(spec, row, links.get(row["id"])))
            count += 1
    orphan_query = select(SearchKey.entity_id)
    for spec in ENTITY_TYPES.values():
        orphan_query = orphan_query.where(SearchKey.entity_id.not_in(select(table_of(spec).c.id)))
    orphans = list(session.execute(orphan_query).scalars())
    if orphans:
        session.execute(delete(SearchKey).where(SearchKey.entity_id.in_(orphans)))
    return count


def _has_letter_or_digit(value: str) -> bool:
    return any(char.isalnum() for char in value)


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def build_match_query(q: str) -> str | None:
    """Build an FTS5 MATCH expression from a user query (DATA_MODEL §10).

    Normalised with :func:`normalize_for_search`; ``"…"`` keeps phrases (exact), every
    other token becomes a prefix query ``"token"*``; tokens without a letter or digit are
    dropped; tokens are joined with AND. Returns None if nothing searchable remains
    (the query then matches nothing). At most 200 characters and 16 tokens.
    """
    if len(q) > MAX_QUERY_CHARS:
        raise ValidationError.single("q", f"must be at most {MAX_QUERY_CHARS} characters")
    terms: list[str] = []
    for match in _TOKEN_RE.finditer(normalize_for_search(q)):
        phrase, word = match.groups()
        if phrase is not None:
            phrase = " ".join(phrase.split())
            if _has_letter_or_digit(phrase):
                terms.append(_quote(phrase))
        elif word is not None and _has_letter_or_digit(word):
            terms.append(_quote(word) + "*")
    if len(terms) > MAX_QUERY_TOKENS:
        raise ValidationError.single("q", f"must have at most {MAX_QUERY_TOKENS} search terms")
    return " AND ".join(terms) if terms else None
