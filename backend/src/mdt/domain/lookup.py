"""``GET /api/lookup`` (docs/API.md §3.1): labels for reference pickers, the global
search box and IDs from shared URLs.

* With ``ids``: the label of every known ID, deleted ones included (``deleted: true``);
  unknown IDs are omitted.
* With ``types`` and ``q``: non-deleted rows whose label, names, slug or alias texts
  start with ``q`` (normalised and case-folded) rank first (exact matches before other
  prefixes), then full-text matches; within a rank, by label. ``f.`` filters apply to
  the requested types that have the field. Without ``q`` the rows are listed by label.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import ColumnElement, Table, case, exists, func, literal, or_, select
from sqlalchemy.orm import Session

from mdt.db.models import Document, Organization, SavedView, SearchKey, Service, VocabularyTerm
from mdt.db.session import read_transaction
from mdt.domain.dates import partial_date_from_columns
from mdt.domain.errors import BadFilterError, ValidationError
from mdt.domain.fieldsql import Source, label_expression
from mdt.domain.fts import build_match_query
from mdt.domain.labels import RefInfo, ref_infos
from mdt.domain.listquery import (
    FieldFilter,
    QueryParams,
    filter_params,
    filterable_field,
    last_param,
    param_pairs,
    parse_filter,
    parse_int_param,
    split_list,
)
from mdt.domain.registry import ENTITY_TYPES, TABLE_TYPES, EntityTypeSpec
from mdt.domain.search import match_subquery
from mdt.domain.text import fold, sortkey

DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100
_EXACT, _PREFIX, _SEARCH = 0, 1, 2


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def lookup(session: Session, params: QueryParams) -> dict[str, Any]:
    """``GET /api/lookup``: ``{"items": [{id, type, label, deleted, context}]}``."""
    pairs = param_pairs(params)
    raw_ids = last_param(pairs, "ids")
    if raw_ids is not None:
        with read_transaction(session):
            return {"items": _items(session, split_list(raw_ids))}
    types = _types(last_param(pairs, "types"))
    limit = parse_int_param("limit", last_param(pairs, "limit"), DEFAULT_LIMIT, 1, MAX_LIMIT)
    filters = _filters_per_type(types, filter_params(pairs))
    q = (last_param(pairs, "q") or "").strip()
    match = build_match_query(q) if q else None
    with read_transaction(session):
        ranked: dict[str, int] = {}
        for spec in types:
            for entity_id, quality in _candidates(
                session, spec, filters[spec.name], q, match, limit
            ):
                ranked.setdefault(entity_id, quality)
        infos = ref_infos(session, ranked)
        order = sorted(
            (entity_id for entity_id in ranked if entity_id in infos),
            key=lambda entity_id: (
                ranked[entity_id],
                sortkey(infos[entity_id].label),
                entity_id,
            ),
        )
        return {"items": _items(session, order[:limit], infos=infos)}


def _types(raw: str | None) -> list[EntityTypeSpec]:
    names = split_list(raw) or list(TABLE_TYPES)
    specs = []
    for name in names:
        spec = ENTITY_TYPES.get(name)
        if spec is None or not spec.generic_api:
            raise ValidationError.single("types", "contains an unknown entity type")
        specs.append(spec)
    return specs


def _filters_per_type(
    types: Sequence[EntityTypeSpec], raw: Mapping[str, str]
) -> dict[str, list[FieldFilter]]:
    """Parse each ``f.`` filter for the requested types that have the field."""
    result: dict[str, list[FieldFilter]] = {spec.name: [] for spec in types}
    for name, value in raw.items():
        applicable = [spec for spec in types if filterable_field(spec, name) is not None]
        if not applicable:
            raise BadFilterError("Unknown or unfilterable filter field")
        for spec in applicable:
            result[spec.name].append(parse_filter(spec.field(name), value))
    return result


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


def _prefix_columns(spec: EntityTypeSpec, table: Table) -> list[ColumnElement[Any]]:
    """Label, name and slug columns compared by prefix (alias texts separately)."""
    columns = table.c
    rule = spec.label_rule
    if rule == "names":
        result: list[ColumnElement[Any]] = [columns.name_en, columns.name_uk]
        return [*result, columns.slug] if "slug" in columns else result
    if rule == "title":
        return [columns.title, columns.title_en]
    if rule == "name":
        return [columns.name]
    if rule == "vocabulary_term":
        return [
            columns.code,
            columns.label_en,
            columns.label_uk,
            columns.vocabulary + ":" + columns.code,
        ]
    return []


def _matching(
    spec: EntityTypeSpec, table: Table, folded: str
) -> tuple[list[ColumnElement[bool]], list[ColumnElement[bool]]]:
    """(prefix conditions, exact conditions) on the label columns and alias texts."""
    prefix: list[ColumnElement[bool]] = []
    exact: list[ColumnElement[bool]] = []
    for column in _prefix_columns(spec, table):
        prefix.append(func.instr(func.mdt_fold(column), folded) == 1)
        exact.append(func.mdt_fold(column) == folded)
    if spec.has_field("aliases"):
        for conditions, compare in ((prefix, "prefix"), (exact, "exact")):
            elements = func.json_each(table.c.aliases).table_valued("value").alias()
            text = func.mdt_fold(func.json_extract(elements.c.value, "$.text"))
            test = func.instr(text, folded) == 1 if compare == "prefix" else text == folded
            conditions.append(exists(select(literal(1)).select_from(elements).where(test)))
    return prefix, exact


def _candidates(
    session: Session,
    spec: EntityTypeSpec,
    filters: Sequence[FieldFilter],
    q: str,
    match: str | None,
    limit: int,
) -> list[tuple[str, int]]:
    """``(id, quality)`` of up to ``limit`` best rows per quality for one type."""
    source = Source(spec)
    table = source.table
    conditions = [table.c.deleted_at.is_(None), *(source.condition(flt) for flt in filters)]
    label_key = func.mdt_sortkey(label_expression(table, spec))
    base = select(table.c.id).select_from(source.from_clause()).where(*conditions)
    if not q:
        rows = session.execute(base.order_by(label_key, table.c.id).limit(limit)).scalars()
        return [(str(entity_id), _EXACT) for entity_id in rows]
    found: list[tuple[str, int]] = []
    prefix, exact = _matching(spec, table, fold(q))
    if prefix:
        quality = case((or_(*exact), _EXACT), else_=_PREFIX)
        statement = (
            base.add_columns(quality)
            .where(or_(*prefix))
            .order_by(quality, label_key, table.c.id)
            .limit(limit)
        )
        found.extend((str(entity_id), int(rank)) for entity_id, rank in session.execute(statement))
    if match is not None:
        known = {entity_id for entity_id, _ in found}
        matches = match_subquery(match, documents=False)
        key = _table(SearchKey).alias()
        statement = (
            base.join(key, key.c.entity_id == table.c.id)
            .join(matches, matches.c.fts_rowid == key.c.rowid)
            .order_by(label_key, table.c.id)
            .limit(limit + len(known))
        )
        found.extend(
            (str(entity_id), _SEARCH)
            for entity_id in session.execute(statement).scalars()
            if entity_id not in known
        )
    return found


# --------------------------------------------------------------------------------------
# Items and contexts
# --------------------------------------------------------------------------------------


def _items(
    session: Session, ids: Sequence[str], *, infos: Mapping[str, RefInfo] | None = None
) -> list[dict[str, Any]]:
    """Lookup items for known IDs in the given order (unknown IDs are omitted)."""
    labels = infos if infos is not None else ref_infos(session, ids)
    known = [labels[entity_id] for entity_id in dict.fromkeys(ids) if entity_id in labels]
    contexts = _contexts(session, known)
    return [{**info.as_dict(), "context": contexts.get(info.id)} for info in known]


def _service_contexts(session: Session, ids: Sequence[str]) -> dict[str, str | None]:
    table = _table(Service)
    statement = select(table.c.id, table.c.project_id).where(table.c.id.in_(ids))
    rows = {str(service): str(project) for service, project in session.execute(statement)}
    projects = ref_infos(session, rows.values())
    return {
        service: projects[project].label if project in projects else None
        for service, project in rows.items()
    }


def _document_contexts(session: Session, ids: Sequence[str]) -> dict[str, str | None]:
    table = _table(Document)
    columns = (
        table.c.publisher,
        table.c.published_start,
        table.c.published_end,
        table.c.published_precision,
    )
    result: dict[str, str | None] = {}
    for entity_id, publisher, start, end, precision in session.execute(
        select(table.c.id, *columns).where(table.c.id.in_(ids))
    ):
        parts = [publisher, partial_date_from_columns(start, end, precision)]
        result[entity_id] = " · ".join(part for part in parts if part) or None
    return result


def _column_contexts(
    model: type[Any], column: str, transform: Callable[[Any], str | None] = lambda v: v
) -> Callable[[Session, Sequence[str]], dict[str, str | None]]:
    def contexts(session: Session, ids: Sequence[str]) -> dict[str, str | None]:
        table = _table(model)
        rows = session.execute(select(table.c.id, table.c[column]).where(table.c.id.in_(ids)))
        return {entity_id: transform(value) if value else None for entity_id, value in rows}

    return contexts


def _type_label(entity_type: str) -> str | None:
    spec = ENTITY_TYPES.get(entity_type)
    return spec.label_plural if spec is not None else entity_type


#: Short disambiguation per type: the project of a service, publisher and date of a
#: document, the English label of a term, the table of a saved view, the country of an
#: organisation. Other types have composed labels and no context.
_CONTEXTS: Final[Mapping[str, Callable[[Session, Sequence[str]], dict[str, str | None]]]] = {
    "service": _service_contexts,
    "document": _document_contexts,
    "vocabulary_term": _column_contexts(VocabularyTerm, "label_en"),
    "saved_view": _column_contexts(SavedView, "entity_type", _type_label),
    "organization": _column_contexts(Organization, "country"),
}


def _contexts(session: Session, infos: Sequence[RefInfo]) -> dict[str, str | None]:
    by_type: dict[str, list[str]] = defaultdict(list)
    for info in infos:
        by_type[info.type].append(info.id)
    result: dict[str, str | None] = {}
    for entity_type, ids in by_type.items():
        builder = _CONTEXTS.get(entity_type)
        if builder is not None:
            result.update(builder(session, ids))
    return result
