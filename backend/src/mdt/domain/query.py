"""List, facet and statistics queries (docs/API.md §3.1, §3.2 and §4).

Filtering, sorting and paging run in SQL; serialisation loads a page in batches
(:mod:`mdt.domain.serialize`). Every public function opens its own read transaction,
so the count and the page come from one snapshot.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import ColumnElement, FromClause, Select, Table, distinct, func, not_, select, true
from sqlalchemy.orm import Session

from mdt.db.models import Comment, DocumentLink, SearchKey, Vocabulary, VocabularyTerm
from mdt.db.session import read_transaction
from mdt.domain.errors import BadFilterError
from mdt.domain.fieldsql import LINK_MATCH_STATES, VIRTUAL_REF_COLUMNS, Source
from mdt.domain.labels import ref_infos
from mdt.domain.listquery import (
    QueryParams,
    Scope,
    SortKey,
    last_param,
    param_pairs,
    parse_list_query,
    parse_scope,
)
from mdt.domain.records import Row, table_of
from mdt.domain.registry import VOCABULARY_TERM, EntityTypeSpec, FieldSpec, generic_types
from mdt.domain.search import match_subquery
from mdt.domain.serialize import generic_spec, load_rows, serialize_items, virtual_values
from mdt.domain.text import sortkey
from mdt.domain.vocab import load_terms

#: Filter kinds that facets are allowed for (API §3.2).
FACET_KINDS: Final = ("multiselect", "bool", "ref")
_BOOL_FACET: Final = (("true", "Yes"), ("false", "No"))


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


@dataclass(frozen=True)
class Selection:
    """The FROM clause and WHERE conditions of a scope; ``rank`` is the FTS rank when
    the scope searches."""

    source: Source
    from_clause: FromClause
    conditions: tuple[ColumnElement[bool], ...]
    rank: ColumnElement[Any] | None

    def count(self) -> Select[Any]:
        """``SELECT count(*)`` of the selected rows."""
        return select(func.count()).select_from(self.from_clause).where(*self.conditions)

    def rows(self, sort: Sequence[SortKey]) -> Select[Any]:
        """The selected rows (every column of the entity table) in sort order."""
        return self._ordered(select(self.source.table), sort)

    def ids(self, sort: Sequence[SortKey]) -> Select[Any]:
        """The IDs of the selected rows in sort order."""
        return self._ordered(select(self.source.table.c.id), sort)

    def _ordered(self, statement: Select[Any], sort: Sequence[SortKey]) -> Select[Any]:
        clauses, joins = self.source.sort_clauses(sort, self.rank)
        from_clause = self.from_clause
        for alias, onclause in joins:
            from_clause = from_clause.outerjoin(alias, onclause)
        return statement.select_from(from_clause).where(*self.conditions).order_by(*clauses)


def select_scope(spec: EntityTypeSpec, scope: Scope) -> Selection | None:
    """The selection of ``scope``, or None if its search text matches nothing."""
    if scope.matches_nothing:
        return None
    source = Source(spec)
    from_clause = source.from_clause()
    conditions = [source.condition(flt) for flt in scope.filters.values()]
    deleted = source.deleted_condition(scope.deleted)
    if deleted is not None:
        conditions.insert(0, deleted)
    rank = None
    if scope.match is not None:
        matches = match_subquery(scope.match, documents=spec.name == "document")
        key = _table(SearchKey).alias("search_key_row")
        from_clause = from_clause.join(key, key.c.entity_id == source.table.c.id).join(
            matches, matches.c.fts_rowid == key.c.rowid
        )
        rank = matches.c.rank
    return Selection(source, from_clause, tuple(conditions), rank)


def iter_row_chunks(
    session: Session,
    selection: Selection,
    sort: Sequence[SortKey],
    chunk_size: int,
) -> Iterator[list[Row]]:
    """Every selected row in sort order, in chunks (used by exports). The ordered IDs
    are read first, so no cursor stays open while a chunk is serialised."""
    ids = [str(entity_id) for entity_id in session.execute(selection.ids(sort)).scalars()]
    for start in range(0, len(ids), chunk_size):
        yield load_rows(session, selection.source.spec, ids[start : start + chunk_size])


# --------------------------------------------------------------------------------------
# GET /api/entities/{type}
# --------------------------------------------------------------------------------------


def list_entities(session: Session, entity_type: str, params: QueryParams) -> dict[str, Any]:
    """``GET /api/entities/{type}``: ``{"items", "total", "page", "page_size"}``."""
    spec = generic_spec(entity_type)
    query = parse_list_query(spec, params)
    with read_transaction(session):
        selection = select_scope(spec, query.scope)
        if selection is None:
            total, rows = 0, []
        else:
            total = int(session.execute(selection.count()).scalar_one())
            statement = selection.rows(query.sort).limit(query.page_size).offset(query.offset)
            rows = [dict(row) for row in session.execute(statement).mappings()]
        items = serialize_items(session, spec, rows, match=query.scope.match)
    return {"items": items, "total": total, "page": query.page, "page_size": query.page_size}


# --------------------------------------------------------------------------------------
# GET /api/entities/{type}/facets
# --------------------------------------------------------------------------------------


def facet_values(session: Session, entity_type: str, params: QueryParams) -> dict[str, Any]:
    """``GET /api/entities/{type}/facets?field=…``: value counts under every filter
    except the one on ``field`` (API §3.2)."""
    spec = generic_spec(entity_type)
    pairs = param_pairs(params)
    name = last_param(pairs, "field")
    field = spec.field_map.get(name or "")
    if field is None or field.internal or field.filter not in FACET_KINDS:
        raise BadFilterError("Facets need a field with a multiselect, bool or ref filter")
    scope = parse_scope(spec, pairs).without(field.name)
    with read_transaction(session):
        selection = select_scope(spec, scope)
        counts, empty_count = _facet_counts(session, field, selection)
        values = _facet_entries(session, field, counts)
    return {"field": field.name, "values": values, "empty_count": empty_count}


def _facet_counts(
    session: Session, field: FieldSpec, selection: Selection | None
) -> tuple[dict[str, int], int]:
    """Counts per value and the number of rows where the field is empty."""
    if selection is None:
        return {}, 0
    source, conditions = selection.source, selection.conditions
    if field.type == "vocab_list":
        column = source.table.c[field.name]
        elements = func.json_each(column).table_valued("value").alias()
        statement = (
            select(elements.c.value, func.count())
            .select_from(selection.from_clause)
            .join(elements, true())
            .where(*conditions)
            .group_by(elements.c.value)
        )
        counts = {str(value): int(count) for value, count in session.execute(statement)}
        empty = selection.count().where(func.json_array_length(column) == 0)
        return counts, int(session.execute(empty).scalar_one())
    if field.type == "doc_links":
        return _link_counts(session, selection)
    if field.virtual and field.name in VIRTUAL_REF_COLUMNS:
        counts = {}
        for name in VIRTUAL_REF_COLUMNS[field.name]:
            column = source.table.c[name]
            statement = (
                selection.count()
                .with_only_columns(column, func.count())
                .where(column.is_not(None))
                .group_by(column)
            )
            for value, count in session.execute(statement):
                counts[value] = counts.get(value, 0) + int(count)
        return counts, 0
    value_expr = source.scalar(field)
    statement = selection.count().with_only_columns(value_expr, func.count()).group_by(value_expr)
    counts = {}
    empty_count = 0
    for value, count in session.execute(statement):
        if value is None:
            empty_count = int(count)
        elif field.type == "bool":
            counts["true" if value else "false"] = int(count)
        else:
            counts[str(value)] = int(count)
    return counts, empty_count


def _link_counts(session: Session, selection: Selection) -> tuple[dict[str, int], int]:
    document_id = selection.source.table.c.id
    link = _table(DocumentLink).alias()
    statement = (
        select(link.c.subject_id, func.count(distinct(document_id)))
        .select_from(
            selection.from_clause.join(
                link,
                (link.c.document_id == document_id) & link.c.state.in_(LINK_MATCH_STATES),
            )
        )
        .where(*selection.conditions)
        .group_by(link.c.subject_id)
    )
    counts = {str(subject): int(count) for subject, count in session.execute(statement)}
    any_link = _table(DocumentLink).alias()
    empty = selection.count().where(
        not_(select(any_link.c.id).where(any_link.c.document_id == document_id).exists())
    )
    return counts, int(session.execute(empty).scalar_one())


def _facet_entries(
    session: Session, field: FieldSpec, counts: dict[str, int]
) -> list[dict[str, Any]]:
    """Facet values with labels: vocabularies in ``sort_order`` with zero counts for
    active terms, booleans as true/false, references labelled and by count."""
    if field.type in ("vocab", "vocab_list"):
        assert field.vocabulary is not None
        terms = load_terms(session, field.vocabulary)
        ordered_terms = sorted(
            terms.values(),
            key=lambda term: (term.sort_order is None, term.sort_order or 0, term.code),
        )
        entries = [
            {"value": term.code, "label": term.label_en, "count": counts.get(term.code, 0)}
            for term in ordered_terms
            if term.active or counts.get(term.code)
        ]
        entries.extend(
            {"value": code, "label": code, "count": count}
            for code, count in sorted(counts.items())
            if code not in terms
        )
        return entries
    if field.type == "bool":
        return [
            {"value": value, "label": label, "count": counts.get(value, 0)}
            for value, label in _BOOL_FACET
        ]
    infos = ref_infos(session, counts)
    labelled = [
        (entity_id, infos[entity_id].label if entity_id in infos else entity_id, count)
        for entity_id, count in counts.items()
    ]
    labelled.sort(key=lambda entry: (-entry[2], sortkey(entry[1]), entry[0]))
    return [
        {"value": entity_id, "label": label, "count": count} for entity_id, label, count in labelled
    ]


# --------------------------------------------------------------------------------------
# GET /api/stats and the usage counts of GET /api/vocab
# --------------------------------------------------------------------------------------


def _open_comment_count(session: Session) -> int:
    comment = _table(Comment)
    statement = (
        select(func.count())
        .select_from(comment)
        .where(
            comment.c.parent_id.is_(None),
            comment.c.status == "open",
            comment.c.deleted_at.is_(None),
        )
    )
    return int(session.execute(statement).scalar_one())


def entity_stats(session: Session) -> dict[str, Any]:
    """``GET /api/stats``: per generic type the live rows (``total``), the live
    unverified rows and the deleted rows, plus the number of open comment threads."""
    entities: dict[str, dict[str, int]] = {}
    with read_transaction(session):
        for spec in generic_types():
            table = table_of(spec)
            live = table.c.deleted_at.is_(None)
            total, unverified, deleted = session.execute(
                select(
                    func.count().filter(live),
                    func.count().filter(live & (table.c.verification_status == "unverified")),
                    func.count().filter(table.c.deleted_at.is_not(None)),
                ).select_from(table)
            ).one()
            entities[spec.name] = {
                "total": int(total),
                "unverified": int(unverified),
                "deleted": int(deleted),
            }
        open_comments = _open_comment_count(session)
    return {"entities": entities, "open_comments": open_comments}


def vocabulary_usage(session: Session) -> dict[tuple[str, str], int]:
    """``usage_count`` per ``(vocabulary, code)``: the number of non-deleted entities
    whose vocabulary fields (stored or derived) contain the code. Runs inside the
    caller's transaction."""
    usage: dict[tuple[str, str], int] = {}
    for spec in generic_types():
        source = Source(spec)
        live = source.table.c.deleted_at.is_(None)
        for field in spec.fields:
            if field.type not in ("vocab", "vocab_list") or field.vocabulary is None:
                continue
            from_clause: FromClause
            if field.type == "vocab_list":
                elements = func.json_each(source.table.c[field.name]).table_valued("value").alias()
                value: ColumnElement[Any] = elements.c.value
                from_clause = source.table.join(elements, true())
            else:
                value = source.scalar(field)
                from_clause = source.from_clause()
            statement = (
                select(value, func.count())
                .select_from(from_clause)
                .where(live, value.is_not(None))
                .group_by(value)
            )
            for code, count in session.execute(statement):
                key = (field.vocabulary, str(code))
                usage[key] = usage.get(key, 0) + int(count)
    return usage


def vocabulary_listing(session: Session) -> dict[str, Any]:
    """``GET /api/vocab``: every vocabulary with its terms in ``sort_order``, each with
    ``usage_count`` and ``open_comments``."""
    term_table = _table(VocabularyTerm)
    with read_transaction(session):
        vocabularies = list(session.scalars(select(Vocabulary).order_by(Vocabulary.name)))
        terms = [
            dict(row)
            for row in session.execute(
                select(term_table).order_by(
                    term_table.c.vocabulary,
                    term_table.c.sort_order.asc().nulls_last(),
                    term_table.c.code,
                )
            ).mappings()
        ]
        usage = vocabulary_usage(session)
        virtual = virtual_values(session, VOCABULARY_TERM, [term["id"] for term in terms])
        by_vocabulary: dict[str, list[dict[str, Any]]] = {}
        for term in terms:
            by_vocabulary.setdefault(term["vocabulary"], []).append(
                {
                    "id": term["id"],
                    "code": term["code"],
                    "label_en": term["label_en"],
                    "label_uk": term["label_uk"],
                    "definition": term["definition"],
                    "include_note": term["include_note"],
                    "exclude_note": term["exclude_note"],
                    "examples": term["examples"],
                    "sort_order": term["sort_order"],
                    "active": bool(term["active"]),
                    "replaced_by": term["replaced_by"],
                    "attributes": term["attributes"] if term["attributes"] is not None else {},
                    "version": term["version"],
                    "usage_count": usage.get((term["vocabulary"], term["code"]), 0),
                    "open_comments": virtual[term["id"]].get("open_comments", 0),
                }
            )
        result = [
            {
                "name": vocabulary.name,
                "label": vocabulary.label,
                "description": vocabulary.description,
                "multi": bool(vocabulary.multi),
                "fixed_codes": bool(vocabulary.fixed_codes),
                "terms": by_vocabulary.get(vocabulary.name, []),
            }
            for vocabulary in vocabularies
        ]
    return {"vocabularies": result}
