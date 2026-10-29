"""Parsing of the list query grammar (docs/API.md §4).

The functions here are pure: they turn request parameters into typed objects and raise
:class:`~mdt.domain.errors.BadFilterError`, :class:`~mdt.domain.errors.BadSortError` or
:class:`~mdt.domain.errors.ValidationError`. SQL is built from the parsed objects by
:mod:`mdt.domain.fieldsql`; request text never becomes SQL.

Parameters arrive as a mapping or as ``(name, value)`` pairs. Starlette's
``request.query_params`` can be passed directly: its ``multi_items()`` are used, so a
repeated ``f.<field>`` parameter is detected.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final

from mdt.domain.dates import PartialDateError, parse_iso_date
from mdt.domain.errors import BadFilterError, BadSortError, ValidationError
from mdt.domain.fts import build_match_query
from mdt.domain.registry import TRASH_DEFAULT_SORT, EntityTypeSpec, FieldSpec
from mdt.domain.text import fold

QueryParams = Mapping[str, str] | Iterable[tuple[str, str]]

#: Reserved list token meaning "the field is empty" (API §4.1).
EMPTY_TOKEN: Final = "~empty"
MAX_FILTER_VALUES: Final = 200
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 500
MAX_PAGE: Final = 1_000_000
MAX_SORT_FIELDS: Final = 3
DELETED_MODES: Final = ("exclude", "only", "include")
RELEVANCE: Final = "relevance"
FILTER_PREFIX: Final = "f."

#: Operators per filter kind (API §4.1). Lists may contain :data:`EMPTY_TOKEN` for the
#: operators in :data:`_EMPTY_TOKEN_OPERATORS`.
_TEXT_OPERATORS: Final = ("contains", "eq", "empty")
_VOCAB_OPERATORS: Final = ("in", "nin", "empty")
_VOCAB_LIST_OPERATORS: Final = ("any", "all", "none", "empty")
_BOOL_OPERATORS: Final = ("eq",)
_DATE_OPERATORS: Final = ("overlaps", "within", "empty")
_NUMBER_OPERATORS: Final = ("range", "eq")
_REF_OPERATORS: Final = ("in", "empty")
_LINK_OPERATORS: Final = ("in", "confirmed", "empty")
_EMPTY_TOKEN_OPERATORS: Final = frozenset({"in", "nin", "any", "none", "confirmed"})

_NUMBER_RE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_PAGE_RE = re.compile(r"^[0-9]{1,9}$")


def param_pairs(params: QueryParams) -> list[tuple[str, str]]:
    """The parameters as ``(name, value)`` pairs, repeated names kept."""
    multi_items = getattr(params, "multi_items", None)
    if callable(multi_items):
        return [(str(name), str(value)) for name, value in multi_items()]
    if isinstance(params, Mapping):
        return [(str(name), str(value)) for name, value in params.items()]
    return [(str(name), str(value)) for name, value in params]


def last_param(pairs: Sequence[tuple[str, str]], name: str) -> str | None:
    """The last value of a non-filter parameter (Starlette semantics), or None."""
    value = None
    for key, item in pairs:
        if key == name:
            value = item
    return value


def split_list(raw: str | None) -> list[str]:
    """A comma-separated parameter as stripped, non-empty, de-duplicated items."""
    if not raw:
        return []
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def operators_for(spec: FieldSpec) -> tuple[str, ...]:
    """The filter operators valid for a field (empty if it has no filter)."""
    kind = spec.filter
    if kind == "text":
        return _TEXT_OPERATORS
    if kind == "multiselect":
        return _VOCAB_LIST_OPERATORS if spec.type == "vocab_list" else _VOCAB_OPERATORS
    if kind == "bool":
        return _BOOL_OPERATORS
    if kind == "date_range":
        return _DATE_OPERATORS
    if kind == "number_range":
        return _NUMBER_OPERATORS
    if kind == "ref":
        return _LINK_OPERATORS if spec.type == "doc_links" else _REF_OPERATORS
    return ()


# --------------------------------------------------------------------------------------
# Parsed objects
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldFilter:
    """One parsed ``f.<field>=<op>:<value>`` filter.

    Only the attributes that belong to the operator are set: ``values`` and
    ``include_empty`` for list operators, ``text`` (folded) for text operators,
    ``flag`` for ``empty:`` and boolean ``eq:``, ``date_from``/``date_to`` for date
    ranges and ``number_min``/``number_max`` for number ranges (``eq:`` sets both).
    """

    field: FieldSpec
    op: str
    values: tuple[str, ...] = ()
    include_empty: bool = False
    text: str = ""
    flag: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    number_min: int | float | None = None
    number_max: int | float | None = None


@dataclass(frozen=True)
class SortKey:
    """One sort field; ``field`` is None for ``relevance``."""

    field: FieldSpec | None
    descending: bool = False

    @property
    def name(self) -> str:
        """The field name (or ``relevance``)."""
        return self.field.name if self.field is not None else RELEVANCE


@dataclass(frozen=True)
class Scope:
    """Which rows a query selects: filters, full-text search and deletion state.

    ``q`` is the search text as given; ``match`` the FTS5 expression built from it.
    With ``q`` set and ``match`` None nothing searchable remained, so nothing matches.
    """

    filters: Mapping[str, FieldFilter] = field(default_factory=dict)
    q: str | None = None
    match: str | None = None
    deleted: str = "exclude"

    @property
    def searching(self) -> bool:
        """True if the query has a search text."""
        return self.q is not None

    @property
    def matches_nothing(self) -> bool:
        """True if the search text left nothing to search for."""
        return self.q is not None and self.match is None

    def without(self, name: str) -> Scope:
        """The same scope without the filter on ``name`` (facets)."""
        return replace(self, filters={k: v for k, v in self.filters.items() if k != name})


@dataclass(frozen=True)
class ListQuery:
    """A parsed list query: scope, sort and page."""

    scope: Scope
    sort: tuple[SortKey, ...]
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        """Rows to skip for the requested page."""
        return (self.page - 1) * self.page_size


# --------------------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------------------


def _bad(spec: FieldSpec, message: str) -> BadFilterError:
    # Field names in messages are registry names, never request text.
    return BadFilterError(f"Filter on {spec.name}: {message}")


def _list_values(spec: FieldSpec, op: str, raw: str) -> tuple[tuple[str, ...], bool]:
    tokens = [token.strip() for token in raw.split(",")]
    tokens = [token for token in tokens if token]
    if len(tokens) > MAX_FILTER_VALUES:
        raise _bad(spec, f"at most {MAX_FILTER_VALUES} values are allowed")
    include_empty = EMPTY_TOKEN in tokens
    if include_empty and op not in _EMPTY_TOKEN_OPERATORS:
        raise _bad(spec, f"{EMPTY_TOKEN} is not allowed with this operator")
    values = tuple(dict.fromkeys(token for token in tokens if token != EMPTY_TOKEN))
    if not values and not include_empty:
        raise _bad(spec, "at least one value is required")
    return values, include_empty


def _flag(spec: FieldSpec, raw: str) -> bool:
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise _bad(spec, "the value must be true or false")


def _date_bound(spec: FieldSpec, raw: str) -> date | None:
    if not raw:
        return None
    try:
        return parse_iso_date(raw)
    except PartialDateError as exc:
        raise _bad(spec, "dates must be valid and written YYYY-MM-DD") from exc


def _number(spec: FieldSpec, raw: str) -> int | float:
    if not _NUMBER_RE.fullmatch(raw):
        raise _bad(spec, "the value must be a number")
    if _INT_RE.fullmatch(raw):
        return int(raw)
    value = float(raw)
    if value in (float("inf"), float("-inf")):
        raise _bad(spec, "the value must be a finite number")
    return value


def _bounds(spec: FieldSpec, raw: str) -> tuple[str, str]:
    low, separator, high = raw.partition("..")
    if not separator:
        raise _bad(spec, "ranges are written <from>..<to>; either bound may be omitted")
    return low.strip(), high.strip()


def parse_filter(spec: FieldSpec, raw: str) -> FieldFilter:
    """Parse the value of ``f.<field>`` (``<op>:<value>``) for a filterable field."""
    op, separator, value = raw.partition(":")
    if not separator:
        raise _bad(spec, "expected <operator>:<value>")
    if op not in operators_for(spec):
        raise _bad(spec, "the operator is not valid for this field")
    if op == "empty":
        return FieldFilter(spec, op, flag=_flag(spec, value))
    kind = spec.filter
    if kind == "text":
        return FieldFilter(spec, op, text=fold(value))
    if kind == "bool":
        return FieldFilter(spec, op, flag=_flag(spec, value))
    if kind == "date_range":
        low, high = _bounds(spec, value)
        date_from, date_to = _date_bound(spec, low), _date_bound(spec, high)
        if date_from and date_to and date_from > date_to:
            raise _bad(spec, "the start of the range is after its end")
        return FieldFilter(spec, op, date_from=date_from, date_to=date_to)
    if kind == "number_range":
        if op == "eq":
            number = _number(spec, value.strip())
            return FieldFilter(spec, op, number_min=number, number_max=number)
        low, high = _bounds(spec, value)
        minimum = _number(spec, low) if low else None
        maximum = _number(spec, high) if high else None
        if minimum is not None and maximum is not None and minimum > maximum:
            raise _bad(spec, "the minimum is larger than the maximum")
        return FieldFilter(spec, op, number_min=minimum, number_max=maximum)
    values, include_empty = _list_values(spec, op, value)
    return FieldFilter(spec, op, values=values, include_empty=include_empty)


def filter_params(pairs: Sequence[tuple[str, str]]) -> dict[str, str]:
    """The ``f.<field>`` parameters by field name; a repeated field is a bad filter."""
    result: dict[str, str] = {}
    for key, value in pairs:
        if not key.startswith(FILTER_PREFIX):
            continue
        name = key[len(FILTER_PREFIX) :]
        if name in result:
            raise BadFilterError("A field may be filtered only once")
        result[name] = value
    return result


def filterable_field(spec: EntityTypeSpec, name: str) -> FieldSpec | None:
    """The field ``name`` of ``spec`` if it can be filtered, else None."""
    field_spec = spec.field_map.get(name)
    if field_spec is None or field_spec.internal or field_spec.filter is None:
        return None
    return field_spec


def parse_filters(spec: EntityTypeSpec, raw: Mapping[str, str]) -> dict[str, FieldFilter]:
    """Parse ``{field: "<op>:<value>"}``; unknown or unfilterable fields are bad filters."""
    filters: dict[str, FieldFilter] = {}
    for name, value in raw.items():
        field_spec = filterable_field(spec, name)
        if field_spec is None:
            raise BadFilterError("Unknown or unfilterable filter field")
        filters[name] = parse_filter(field_spec, value)
    return filters


# --------------------------------------------------------------------------------------
# Search, deletion state, paging and sorting
# --------------------------------------------------------------------------------------


def parse_search(raw: str | None) -> tuple[str | None, str | None]:
    """``(q, match)``: a blank search is no search; see :func:`build_match_query`."""
    if raw is None or not raw.strip():
        return None, None
    return raw, build_match_query(raw)


def parse_deleted(raw: str | None) -> str:
    """The ``deleted`` mode (default ``exclude``)."""
    if raw is None or raw == "":
        return "exclude"
    if raw not in DELETED_MODES:
        raise ValidationError.single("deleted", f"must be one of {', '.join(DELETED_MODES)}")
    return raw


def parse_int_param(name: str, raw: str | None, default: int, minimum: int, maximum: int) -> int:
    """A positive integer parameter within ``[minimum, maximum]``."""
    if raw is None or raw == "":
        return default
    if not _PAGE_RE.fullmatch(raw) or not minimum <= int(raw) <= maximum:
        raise ValidationError.single(name, f"must be an integer from {minimum} to {maximum}")
    return int(raw)


def parse_paging(pairs: Sequence[tuple[str, str]]) -> tuple[int, int]:
    """``(page, page_size)`` with the defaults and limits of API §4.3."""
    page = parse_int_param("page", last_param(pairs, "page"), 1, 1, MAX_PAGE)
    page_size = parse_int_param(
        "page_size", last_param(pairs, "page_size"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE
    )
    return page, page_size


def parse_sort(spec: EntityTypeSpec, raw: str, *, searching: bool) -> tuple[SortKey, ...]:
    """Parse ``field[,-field2[,field3]]``: at most three sortable fields, or ``relevance``
    together with a search text."""
    keys: list[SortKey] = []
    seen: set[str] = set()
    for item in raw.split(","):
        token = item.strip()
        descending = token.startswith("-")
        name = token[1:] if descending else token
        if not name:
            raise BadSortError("Empty sort field")
        if name in seen:
            raise BadSortError("A field may appear only once in the sort")
        seen.add(name)
        if name == RELEVANCE:
            if not searching:
                raise BadSortError("Sorting by relevance needs a search text (q)")
            keys.append(SortKey(None, descending))
            continue
        field_spec = spec.field_map.get(name)
        if field_spec is None or field_spec.internal or not field_spec.sortable:
            raise BadSortError("Unknown or unsortable sort field")
        keys.append(SortKey(field_spec, descending))
    if len(keys) > MAX_SORT_FIELDS:
        raise BadSortError(f"At most {MAX_SORT_FIELDS} sort fields are allowed")
    return tuple(keys)


def default_sort(spec: EntityTypeSpec, deleted: str) -> str:
    """The default sort: the trash sorts by deletion time, other views per type."""
    return TRASH_DEFAULT_SORT if deleted == "only" else spec.default_sort


def parse_scope(spec: EntityTypeSpec, pairs: Sequence[tuple[str, str]]) -> Scope:
    """Filters, ``q`` and ``deleted`` of a request (no paging or sorting)."""
    filters = parse_filters(spec, filter_params(pairs))
    q, match = parse_search(last_param(pairs, "q"))
    return Scope(filters, q, match, parse_deleted(last_param(pairs, "deleted")))


def parse_sort_param(
    spec: EntityTypeSpec, pairs: Sequence[tuple[str, str]], scope: Scope
) -> tuple[SortKey, ...]:
    """The requested sort, or the default when ``sort`` is missing or blank."""
    raw = last_param(pairs, "sort")
    if raw is None or not raw.strip():
        raw = default_sort(spec, scope.deleted)
    return parse_sort(spec, raw, searching=scope.searching)


def parse_list_query(spec: EntityTypeSpec, params: QueryParams) -> ListQuery:
    """Parse every list parameter of API §4 for ``spec``."""
    pairs = param_pairs(params)
    scope = parse_scope(spec, pairs)
    page, page_size = parse_paging(pairs)
    return ListQuery(scope, parse_sort_param(spec, pairs, scope), page, page_size)
