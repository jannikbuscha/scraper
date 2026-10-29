"""SQL expressions for registry fields: filters, sort keys and virtual values.

Implements the filter semantics and sort keys of docs/API.md §4.1-§4.2 on top of the
entity tables. Field names map to column expressions of the registry; values from
requests are always bound parameters (``json_each`` paths and vocabulary names are
constants or registry values).

* Derived fields (project, service) come from a LEFT JOIN on ``derived``; a missing row
  counts as ``unknown`` (DATA_MODEL §8.1).
* Virtual fields are correlated subqueries (DATA_MODEL §2.4), so they filter and sort
  like stored fields; :meth:`Source.virtual_columns` evaluates them for a page of IDs.
* NULLs (and empty lists) sort last in both directions; the final tie-breaker is ``id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    FromClause,
    Integer,
    Select,
    Table,
    Text,
    UnaryExpression,
    and_,
    case,
    distinct,
    exists,
    false,
    func,
    literal,
    not_,
    or_,
    select,
    true,
    type_coerce,
)

from mdt.db.models import Comment, Derived, DocumentLink, Project, Service, VocabularyTerm
from mdt.domain.listquery import FieldFilter, SortKey
from mdt.domain.records import table_of
from mdt.domain.registry import ENTITY_TYPES, EntityTypeSpec, FieldSpec

#: Link states that ``in:`` matches on document links (``confirmed:`` only confirmed).
LINK_MATCH_STATES: Final = ("suggested", "confirmed")
#: Value of derived vocabulary fields without a derived row (DATA_MODEL §8.1).
DERIVED_UNKNOWN: Final = "unknown"
#: Virtual reference fields used as filters only: the columns they match.
VIRTUAL_REF_COLUMNS: Final = {"endpoint": ("from_id", "to_id")}
#: Virtual fields that can be evaluated per row.
VALUE_VIRTUALS: Final = frozenset(
    {
        "open_comments",
        "comment_count",
        "project_in_paper_scope",
        "subject_in_paper_scope",
        "linked_in_paper_scope",
    }
)
_DERIVED_VOCABS: Final = frozenset({"period", "war_trajectory"})

Join = tuple[FromClause, ColumnElement[bool]]


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def ordered(expression: ColumnElement[Any], descending: bool) -> UnaryExpression[Any]:
    """``expression ASC|DESC NULLS LAST``."""
    direction = expression.desc() if descending else expression.asc()
    return direction.nulls_last()


def label_expression(alias: FromClause, spec: EntityTypeSpec) -> ColumnElement[Any]:
    """The label of a row of ``spec`` in SQL, for sorting by reference (API §4.2):
    name_en → name_uk → slug for named types, the title of documents, the name of saved
    views. Types whose labels are composed from other records fall back to the ID."""
    columns = alias.c
    rule = spec.label_rule
    if rule == "names":
        parts = [columns.name_en, columns.name_uk]
        if "slug" in columns:
            parts.append(columns.slug)
        return func.coalesce(*parts, columns.id)
    if rule == "title":
        return func.coalesce(columns.title, columns.id)
    if rule == "name":
        return func.coalesce(columns.name, columns.id)
    if rule == "vocabulary_term":
        return columns.vocabulary + ":" + columns.code
    return columns.id


# --------------------------------------------------------------------------------------
# Shared semantics of virtual fields (DATA_MODEL §2.4, §3.2-§3.4)
# --------------------------------------------------------------------------------------


def open_comments_expression(entity_id: ColumnElement[Any]) -> ColumnElement[Any]:
    """Non-deleted open root comments on the entity (field threads included)."""
    comment = _table(Comment).alias()
    return (
        select(func.count())
        .select_from(comment)
        .where(
            comment.c.subject_id == entity_id,
            comment.c.parent_id.is_(None),
            comment.c.status == "open",
            comment.c.deleted_at.is_(None),
        )
        .scalar_subquery()
    )


def comment_count_expression(entity_id: ColumnElement[Any]) -> ColumnElement[Any]:
    """Visible comments on the entity, replies included: non-deleted comments outside
    deleted threads (deleting a root hides its thread, DATA_MODEL §6.6)."""
    comment = _table(Comment).alias()
    root = _table(Comment).alias()
    return (
        select(func.count())
        .select_from(comment.outerjoin(root, root.c.id == comment.c.parent_id))
        .where(
            comment.c.subject_id == entity_id,
            comment.c.deleted_at.is_(None),
            or_(comment.c.parent_id.is_(None), root.c.deleted_at.is_(None)),
        )
        .scalar_subquery()
    )


def in_scope_project_ids() -> Select[Any]:
    """IDs of projects in the paper's scope."""
    project = _table(Project).alias()
    return select(project.c.id).where(project.c.in_paper_scope.is_(true()))


def in_scope_service_ids() -> Select[Any]:
    """IDs of services whose project is in the paper's scope."""
    service = _table(Service).alias()
    project = _table(Project).alias()
    return (
        select(service.c.id)
        .join(project, project.c.id == service.c.project_id)
        .where(project.c.in_paper_scope.is_(true()))
    )


def subject_in_scope(subject_id: ColumnElement[Any]) -> ColumnElement[bool]:
    """The subject is an in-scope project or a service of one."""
    return or_(subject_id.in_(in_scope_project_ids()), subject_id.in_(in_scope_service_ids()))


def linked_in_scope(document_id: ColumnElement[Any]) -> ColumnElement[bool]:
    """A confirmed link points to an in-scope project or one of its services."""
    link = _table(DocumentLink).alias()
    return exists().where(
        link.c.document_id == document_id,
        link.c.state == "confirmed",
        subject_in_scope(link.c.subject_id),
    )


def _as_flag(condition: ColumnElement[bool]) -> ColumnElement[Any]:
    return case((condition, 1), else_=0)


def _json_elements(column: ColumnElement[Any]) -> Any:
    return func.json_each(column).table_valued("value").alias()


# --------------------------------------------------------------------------------------
# Source: the FROM side of a query on one entity type
# --------------------------------------------------------------------------------------


class Source:
    """Expressions of one entity type's fields over its table (and, for project and
    service, the LEFT JOINed ``derived`` row)."""

    def __init__(self, spec: EntityTypeSpec) -> None:
        self.spec = spec
        self.table = table_of(spec)
        self.derived = _table(Derived).alias("derived_row") if spec.has_derived else None

    def from_clause(self) -> FromClause:
        """The entity table, LEFT JOIN ``derived`` where the type has derived values."""
        if self.derived is None:
            return self.table
        return self.table.outerjoin(self.derived, self.derived.c.entity_id == self.table.c.id)

    def deleted_condition(self, mode: str) -> ColumnElement[bool] | None:
        """``exclude`` → live rows, ``only`` → deleted rows, ``include`` → all."""
        if mode == "exclude":
            return self.table.c.deleted_at.is_(None)
        if mode == "only":
            return self.table.c.deleted_at.is_not(None)
        return None

    # ---------------------------------------------------------------- values

    def scalar(self, field: FieldSpec) -> ColumnElement[Any]:
        """The value of a scalar field (stored, system, derived or virtual)."""
        if field.derived:
            assert self.derived is not None
            if field.name in _DERIVED_VOCABS:
                return func.coalesce(self.derived.c[field.name], DERIVED_UNKNOWN)
            return self.derived.c[field.name]
        if field.virtual:
            return self.virtual(field.name)
        return self.table.c[field.name]

    def interval(self, field: FieldSpec) -> tuple[ColumnElement[Any], ColumnElement[Any]]:
        """``(start, end)`` of a partial date (stored or derived) or a calendar date."""
        if field.type == "partial_date":
            columns = self.derived.c if field.derived and self.derived is not None else self.table.c
            return columns[f"{field.name}_start"], columns[f"{field.name}_end"]
        value = self.scalar(field)
        return value, value

    def virtual(self, name: str) -> ColumnElement[Any]:
        """The value expression of a virtual field (bools as 0/1)."""
        columns = self.table.c
        if name == "open_comments":
            return open_comments_expression(columns.id)
        if name == "comment_count":
            return comment_count_expression(columns.id)
        if name == "project_in_paper_scope":
            return _as_flag(columns.project_id.in_(in_scope_project_ids()))
        if name == "subject_in_paper_scope":
            return _as_flag(subject_in_scope(columns.subject_id))
        if name == "linked_in_paper_scope":
            return _as_flag(linked_in_scope(columns.id))
        raise ValueError(f"virtual field {name} has no value expression")

    def virtual_columns(self) -> list[tuple[str, ColumnElement[Any]]]:
        """``(name, expression)`` of every virtual field with a per-row value."""
        return [
            (field.name, self.virtual(field.name))
            for field in self.spec.fields
            if field.virtual and field.name in VALUE_VIRTUALS
        ]

    # ---------------------------------------------------------------- filters

    def condition(self, flt: FieldFilter) -> ColumnElement[bool]:
        """The WHERE condition of one parsed filter (API §4.1)."""
        field = flt.field
        kind = field.filter
        if kind == "text":
            return self._text(flt)
        if kind == "multiselect":
            return self._vocab_list(flt) if field.type == "vocab_list" else self._vocab(flt)
        if kind == "bool":
            value = type_coerce(self.scalar(field), Integer)
            return value == (1 if flt.flag else 0)
        if kind == "date_range":
            return self._date_range(flt)
        if kind == "number_range":
            return self._number_range(flt)
        if kind == "ref":
            if field.type == "doc_links":
                return self._links(flt)
            return self._ref(flt)
        raise ValueError(f"field {field.name} has no filter")

    def _text(self, flt: FieldFilter) -> ColumnElement[bool]:
        field = flt.field
        if field.is_list:
            column = self.table.c[field.name]
            if flt.op == "empty":
                length = func.json_array_length(column)
                return length == 0 if flt.flag else length > 0
            elements = _json_elements(column)
            element = elements.c.value
            if field.type == "alias_list":
                element = func.json_extract(element, "$.text")
            matching = select(literal(1)).select_from(elements).where(_text_match(element, flt))
            return exists(matching)
        value = self.scalar(field)
        if flt.op == "empty":
            return value.is_(None) if flt.flag else value.is_not(None)
        return _text_match(value, flt)

    def _vocab(self, flt: FieldFilter) -> ColumnElement[bool]:
        value = self.scalar(flt.field)
        if flt.op == "empty":
            return value.is_(None) if flt.flag else value.is_not(None)
        values = list(flt.values)
        if flt.op == "in":
            options = [value.in_(values)] if values else []
            if flt.include_empty:
                options.append(value.is_(None))
            return or_(*options)
        # nin: rows whose field is empty are included, unless ~empty is listed.
        outside = or_(value.not_in(values), value.is_(None)) if values else true()
        return and_(outside, value.is_not(None)) if flt.include_empty else outside

    def _vocab_list(self, flt: FieldFilter) -> ColumnElement[bool]:
        column = self.table.c[flt.field.name]
        length = func.json_array_length(column)
        if flt.op == "empty":
            return length == 0 if flt.flag else length > 0
        values = list(flt.values)
        elements = _json_elements(column)
        if flt.op == "all":
            found = (
                select(func.count(distinct(elements.c.value)))
                .select_from(elements)
                .where(elements.c.value.in_(values))
                .scalar_subquery()
            )
            return found == len(values)
        any_of = (
            exists(select(literal(1)).select_from(elements).where(elements.c.value.in_(values)))
            if values
            else false()
        )
        if flt.op == "any":
            return or_(any_of, length == 0) if flt.include_empty else any_of
        # none: empty lists are included, unless ~empty is listed.
        return and_(not_(any_of), length > 0) if flt.include_empty else not_(any_of)

    def _date_range(self, flt: FieldFilter) -> ColumnElement[bool]:
        field = flt.field
        if field.type == "datetime":
            return self._datetime_range(flt)
        start, end = self.interval(field)
        if flt.op == "empty":
            return start.is_(None) if flt.flag else start.is_not(None)
        conditions: list[ColumnElement[bool]] = [start.is_not(None)]
        low = flt.date_from.isoformat() if flt.date_from else None
        high = flt.date_to.isoformat() if flt.date_to else None
        if flt.op == "overlaps":
            if high is not None:
                conditions.append(start <= high)
            if low is not None:
                conditions.append(end >= low)
        else:
            if low is not None:
                conditions.append(start >= low)
            if high is not None:
                conditions.append(end <= high)
        return and_(*conditions)

    def _datetime_range(self, flt: FieldFilter) -> ColumnElement[bool]:
        # A timestamp is the one-day interval of its UTC calendar date, so overlaps and
        # within coincide. Text comparison keeps the index usable.
        value = type_coerce(self.scalar(flt.field), Text)
        if flt.op == "empty":
            return value.is_(None) if flt.flag else value.is_not(None)
        conditions: list[ColumnElement[bool]] = [value.is_not(None)]
        if flt.date_from is not None:
            conditions.append(value >= flt.date_from.isoformat())
        if flt.date_to is not None and flt.date_to < date.max:
            conditions.append(value < (flt.date_to + timedelta(days=1)).isoformat())
        return and_(*conditions)

    def _number_range(self, flt: FieldFilter) -> ColumnElement[bool]:
        value = self.scalar(flt.field)
        if flt.op == "eq":
            return value == flt.number_min
        conditions: list[ColumnElement[bool]] = [value.is_not(None)]
        if flt.number_min is not None:
            conditions.append(value >= flt.number_min)
        if flt.number_max is not None:
            conditions.append(value <= flt.number_max)
        return and_(*conditions)

    def _ref(self, flt: FieldFilter) -> ColumnElement[bool]:
        field = flt.field
        names = VIRTUAL_REF_COLUMNS.get(field.name, ()) if field.virtual else (field.name,)
        columns = [self.table.c[name] for name in names]
        if flt.op == "empty":
            empty = and_(*(column.is_(None) for column in columns))
            return empty if flt.flag else not_(empty)
        values = list(flt.values)
        options: list[ColumnElement[bool]] = []
        if values:
            options.extend(column.in_(values) for column in columns)
        if flt.include_empty:
            options.extend(column.is_(None) for column in columns)
        return or_(*options)

    def _links(self, flt: FieldFilter) -> ColumnElement[bool]:
        document_id = self.table.c.id
        link = _table(DocumentLink).alias()
        any_link = exists().where(link.c.document_id == document_id)
        if flt.op == "empty":
            return not_(any_link) if flt.flag else any_link
        states = ("confirmed",) if flt.op == "confirmed" else LINK_MATCH_STATES
        options: list[ColumnElement[bool]] = []
        if flt.values:
            matching = _table(DocumentLink).alias()
            options.append(
                exists().where(
                    matching.c.document_id == document_id,
                    matching.c.subject_id.in_(list(flt.values)),
                    matching.c.state.in_(states),
                )
            )
        if flt.include_empty:
            options.append(not_(any_link))
        return or_(*options)

    # ---------------------------------------------------------------- sorting

    def sort_clauses(
        self, keys: Sequence[SortKey], rank: ColumnElement[Any] | None
    ) -> tuple[list[UnaryExpression[Any]], list[Join]]:
        """ORDER BY clauses for the sort keys plus the tie-breaker ``id``, and the LEFT
        JOINs that reference labels need."""
        clauses: list[UnaryExpression[Any]] = []
        joins: list[Join] = []
        for index, key in enumerate(keys):
            if key.field is None:
                if rank is None:
                    raise ValueError("relevance sorting needs a search")
                clauses.append(ordered(rank, key.descending))
                continue
            field_clauses, field_joins = self._field_order(key.field, key.descending, index)
            clauses.extend(field_clauses)
            joins.extend(field_joins)
        clauses.append(self.table.c.id.asc())
        return clauses, joins

    def _field_order(
        self, field: FieldSpec, descending: bool, index: int
    ) -> tuple[list[UnaryExpression[Any]], list[Join]]:
        kind = field.type
        if kind == "partial_date":
            start, end = self.interval(field)
            return [ordered(start, descending), ordered(end, descending)], []
        if kind in ("vocab", "vocab_list"):
            return self._vocab_order(field, descending), []
        if kind == "ref":
            return self._ref_order(field, descending, index)
        value = self.scalar(field)
        if kind in ("string", "text"):
            value = func.mdt_sortkey(value)
        elif kind == "bool":
            value = type_coerce(value, Integer)
        return [ordered(value, descending)], []

    def _vocab_order(self, field: FieldSpec, descending: bool) -> list[UnaryExpression[Any]]:
        value = (
            func.json_extract(self.table.c[field.name], "$[0]")
            if field.type == "vocab_list"
            else self.scalar(field)
        )
        term = _table(VocabularyTerm).alias()
        sort_order = (
            select(term.c.sort_order)
            .where(term.c.vocabulary == field.vocabulary, term.c.code == value)
            .correlate_except(term)
            .scalar_subquery()
        )
        return [ordered(sort_order, descending), ordered(value, descending)]

    def _ref_order(
        self, field: FieldSpec, descending: bool, index: int
    ) -> tuple[list[UnaryExpression[Any]], list[Join]]:
        column = self.table.c[field.name]
        joins: list[Join] = []
        labels: list[ColumnElement[Any]] = []
        for type_name in field.ref_types or ():
            target = ENTITY_TYPES[type_name]
            alias = table_of(target).alias(f"sort{index}_{type_name}")
            joins.append((alias, alias.c.id == column))
            labels.append(label_expression(alias, target))
        label = labels[0] if len(labels) == 1 else func.coalesce(*labels)
        return [ordered(func.mdt_sortkey(label), descending)], joins


def _text_match(value: ColumnElement[Any], flt: FieldFilter) -> ColumnElement[bool]:
    folded = func.mdt_fold(value)
    if flt.op == "eq":
        return folded == flt.text
    return func.instr(folded, flt.text) > 0
