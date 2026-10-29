"""Full-text search in list queries (docs/DATA_MODEL.md §10, docs/API.md §2 and §4.3).

The MATCH expression comes from :func:`mdt.domain.fts.build_match_query`; it is always a
bound parameter. For documents ``q`` matches ``fts_entity`` (metadata) OR
``fts_document`` (title and full text); every other type matches ``fts_entity``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final

from sqlalchemy import Float, Integer, Subquery, bindparam, column, text
from sqlalchemy.orm import Session

SNIPPET_OPEN: Final = "\ue000"
SNIPPET_CLOSE: Final = "\ue001"
SNIPPET_ELLIPSIS: Final = "…"
SNIPPET_TOKENS: Final = 24

_ENTITY_MATCH = (
    "SELECT rowid AS fts_rowid, bm25(fts_entity) AS rank FROM fts_entity "
    "WHERE fts_entity MATCH :match"
)
_DOCUMENT_MATCH = (
    "SELECT fts_rowid, min(rank) AS rank FROM ("
    "SELECT rowid AS fts_rowid, bm25(fts_entity) AS rank FROM fts_entity "
    "WHERE fts_entity MATCH :match "
    "UNION ALL "
    "SELECT rowid AS fts_rowid, bm25(fts_document) AS rank FROM fts_document "
    "WHERE fts_document MATCH :match"
    ") GROUP BY fts_rowid"
)
_SNIPPET_SQL = (
    "SELECT search_key.entity_id, snippet({table}, -1, :open, :close, :ellipsis, :tokens) "
    "FROM {table} JOIN search_key ON search_key.rowid = {table}.rowid "
    "WHERE {table} MATCH :match AND search_key.entity_id IN :ids"
)


def match_subquery(match: str, *, documents: bool) -> Subquery:
    """``(fts_rowid, rank)`` of every FTS row matching ``match``; ``rank`` is FTS5
    ``bm25`` (lower is better). For documents the better rank of both tables counts."""
    sql = _DOCUMENT_MATCH if documents else _ENTITY_MATCH
    return (
        text(sql)
        .bindparams(match=match)
        .columns(column("fts_rowid", Integer), column("rank", Float))
        .subquery("fts_match")
    )


def snippet_segments(raw: str) -> list[dict[str, Any]]:
    """Split an FTS snippet with the private-use markers into
    ``[{"text": …, "hit": bool}, …]``; markup is never sent (DATA_MODEL §10)."""
    segments: list[dict[str, Any]] = []
    buffer: list[str] = []
    hit = False

    def flush() -> None:
        if not buffer:
            return
        chunk = "".join(buffer)
        buffer.clear()
        if segments and segments[-1]["hit"] == hit:
            segments[-1]["text"] += chunk
        else:
            segments.append({"text": chunk, "hit": hit})

    for char in raw:
        if char in (SNIPPET_OPEN, SNIPPET_CLOSE):
            flush()
            hit = char == SNIPPET_OPEN
        else:
            buffer.append(char)
    flush()
    return segments


def _snippets(
    session: Session, table: str, entity_ids: Sequence[str], match: str
) -> dict[str, list[dict[str, Any]]]:
    statement = text(_SNIPPET_SQL.format(table=table)).bindparams(
        bindparam("ids", expanding=True),
        match=match,
        open=SNIPPET_OPEN,
        close=SNIPPET_CLOSE,
        ellipsis=SNIPPET_ELLIPSIS,
        tokens=SNIPPET_TOKENS,
    )
    rows = session.execute(statement, {"ids": list(entity_ids)})
    return {entity_id: snippet_segments(raw or "") for entity_id, raw in rows}


def document_snippets(
    session: Session, entity_ids: Iterable[str], match: str
) -> dict[str, list[dict[str, Any]]]:
    """Search snippets of documents: from the title and full text where they match,
    otherwise from the metadata (``fts_entity``)."""
    ids = list(dict.fromkeys(entity_ids))
    if not ids:
        return {}
    result = _snippets(session, "fts_document", ids, match)
    missing = [entity_id for entity_id in ids if entity_id not in result]
    if missing:
        result.update(_snippets(session, "fts_entity", missing, match))
    return result
