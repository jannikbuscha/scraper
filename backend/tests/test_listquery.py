"""Parsing of the list query grammar (docs/API.md §4), without a database."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any

import pytest

from mdt.domain.errors import BadFilterError, BadSortError, ValidationError
from mdt.domain.listquery import (
    EMPTY_TOKEN,
    FieldFilter,
    Scope,
    operators_for,
    param_pairs,
    parse_filter,
    parse_list_query,
    split_list,
)
from mdt.domain.registry import DOCUMENT, ENTITY_TYPES, EVENT, PROJECT, RELATION, SERVICE


def flt(spec_name: str, field: str, raw: str) -> FieldFilter:
    return parse_filter(ENTITY_TYPES[spec_name].field(field), raw)


class _MultiDict(Mapping[str, str]):
    """Mimics Starlette's QueryParams: a mapping (last value wins) whose
    ``multi_items()`` keep repeated names."""

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._items = items
        self._last = dict(items)

    def __getitem__(self, key: str) -> str:
        return self._last[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._last)

    def __len__(self) -> int:
        return len(self._last)

    def multi_items(self) -> list[tuple[str, str]]:
        return list(self._items)


# --------------------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------------------


def test_param_pairs_accepts_mappings_pairs_and_multidicts() -> None:
    assert param_pairs({"a": "1"}) == [("a", "1")]
    assert param_pairs([("a", "1"), ("a", "2")]) == [("a", "1"), ("a", "2")]
    assert param_pairs(_MultiDict([("f.x", "1"), ("f.x", "2")])) == [("f.x", "1"), ("f.x", "2")]


def test_split_list_strips_drops_empty_items_and_duplicates() -> None:
    assert split_list(" a, b,,a ,") == ["a", "b"]
    assert split_list(None) == []


def test_repeated_filter_is_a_bad_filter() -> None:
    with pytest.raises(BadFilterError):
        parse_list_query(PROJECT, _MultiDict([("f.status", "in:a"), ("f.status", "in:b")]))


@pytest.mark.parametrize(
    "params",
    [
        {"f.unknown": "eq:x"},
        {"f.seed_key": "eq:x"},  # internal
        {"f.version": "range:1.."},  # no filter
        {"f.archive_urls": "contains:x"},  # filter None in the registry
    ],
)
def test_unknown_or_unfilterable_fields_are_bad_filters(params: dict[str, str]) -> None:
    spec = DOCUMENT if "archive_urls" in str(params) else PROJECT
    with pytest.raises(BadFilterError):
        parse_list_query(spec, params)


def test_document_text_is_not_filterable() -> None:
    with pytest.raises(BadFilterError):
        parse_list_query(DOCUMENT, {"f.text": "contains:x"})


# --------------------------------------------------------------------------------------
# Operators per filter kind
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec_name", "field", "operators"),
    [
        ("project", "name_en", ("contains", "eq", "empty")),
        ("project", "status", ("in", "nin", "empty")),
        ("project", "policy_domains", ("any", "all", "none", "empty")),
        ("project", "in_paper_scope", ("eq",)),
        ("project", "launch", ("overlaps", "within", "empty")),
        ("project", "open_comments", ("range", "eq")),
        ("service", "project_id", ("in", "empty")),
        ("document", "links", ("in", "confirmed", "empty")),
        ("relation", "endpoint", ("in", "empty")),
    ],
)
def test_operators_per_kind(spec_name: str, field: str, operators: tuple[str, ...]) -> None:
    assert operators_for(ENTITY_TYPES[spec_name].field(field)) == operators


@pytest.mark.parametrize(
    ("spec_name", "field", "raw"),
    [
        ("project", "name_en", "in:a"),
        ("project", "status", "contains:a"),
        ("project", "status", "any:a"),
        ("project", "policy_domains", "in:a"),
        ("project", "in_paper_scope", "empty:true"),
        ("project", "launch", "range:1..2"),
        ("service", "project_id", "confirmed:prj_x"),
        ("project", "open_comments", "in:1"),
    ],
)
def test_invalid_operator_is_a_bad_filter(spec_name: str, field: str, raw: str) -> None:
    with pytest.raises(BadFilterError):
        flt(spec_name, field, raw)


def test_missing_operator_separator_is_a_bad_filter() -> None:
    with pytest.raises(BadFilterError):
        flt("project", "name_en", "Alpha")


def test_bad_filter_messages_name_the_field_but_not_the_value() -> None:
    with pytest.raises(BadFilterError) as caught:
        flt("project", "launch", "within:2022-13-01..")
    assert "launch" in caught.value.message
    assert "2022-13-01" not in caught.value.message


# --------------------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------------------


def test_text_value_is_the_whole_remainder_after_the_first_colon() -> None:
    parsed = flt("evidence", "target", "eq:field:name_en")
    assert (parsed.op, parsed.text) == ("eq", "field:name_en")


def test_text_value_is_folded_like_indexed_text() -> None:
    # Cyrillic case folding and apostrophe variants (U+2019 → U+02BC).
    parsed = flt("project", "name_uk", "contains:З\u2019ЯВИЛАСЯ")
    assert parsed.text == "з\u02bcявилася"


def test_text_value_keeps_commas_and_spaces() -> None:
    assert flt("project", "name_en", "contains: a, b ").text == " a, b "


# --------------------------------------------------------------------------------------
# Lists and the ~empty token
# --------------------------------------------------------------------------------------


def test_list_values_are_split_deduplicated_and_empty_token_detected() -> None:
    parsed = flt("project", "status", f"in:active, planned,active,{EMPTY_TOKEN}")
    assert parsed.values == ("active", "planned")
    assert parsed.include_empty is True


def test_empty_token_alone_is_allowed() -> None:
    parsed = flt("project", "status", f"nin:{EMPTY_TOKEN}")
    assert (parsed.values, parsed.include_empty) == ((), True)


def test_empty_token_with_all_is_a_bad_filter() -> None:
    with pytest.raises(BadFilterError):
        flt("project", "policy_domains", f"all:domain_a,{EMPTY_TOKEN}")


def test_empty_token_is_allowed_for_ref_and_link_lists() -> None:
    assert flt("service", "parent_service_id", f"in:{EMPTY_TOKEN}").include_empty
    assert flt("document", "links", f"confirmed:prj_x,{EMPTY_TOKEN}").include_empty


@pytest.mark.parametrize("raw", ["in:", "in:,,", "any: , "])
def test_empty_list_is_a_bad_filter(raw: str) -> None:
    field = "policy_domains" if raw.startswith("any") else "status"
    with pytest.raises(BadFilterError):
        flt("project", field, raw)


# --------------------------------------------------------------------------------------
# empty:, booleans, dates and numbers
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [("empty:true", True), ("empty:false", False)])
def test_empty_operator(raw: str, expected: bool) -> None:
    assert flt("project", "name_en", raw).flag is expected


@pytest.mark.parametrize("raw", ["empty:yes", "empty:", "empty:TRUE"])
def test_empty_operator_needs_true_or_false(raw: str) -> None:
    with pytest.raises(BadFilterError):
        flt("project", "status", raw)


def test_bool_filter() -> None:
    assert flt("project", "in_paper_scope", "eq:true").flag is True
    assert flt("service", "project_in_paper_scope", "eq:false").flag is False
    with pytest.raises(BadFilterError):
        flt("project", "in_paper_scope", "eq:1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("overlaps:2016-03-01..2016-03-31", (date(2016, 3, 1), date(2016, 3, 31))),
        ("within:..2011-07-14", (None, date(2011, 7, 14))),
        ("within:2016-03-10..", (date(2016, 3, 10), None)),
        ("overlaps:..", (None, None)),
    ],
)
def test_date_ranges_with_open_bounds(raw: str, expected: tuple[Any, Any]) -> None:
    parsed = flt("event", "date", raw)
    assert (parsed.date_from, parsed.date_to) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "within:2022-02-30..",  # not a calendar date
        "within:2022-2-1..",  # not YYYY-MM-DD
        "within:2022",  # no range separator
        "overlaps:2016-04-01..2016-03-01",  # start after end
        "within:2022-02-01T00:00..",
    ],
)
def test_malformed_date_ranges(raw: str) -> None:
    with pytest.raises(BadFilterError):
        flt("event", "date", raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("range:1..", (1, None)),
        ("range:..5.5", (None, 5.5)),
        ("range:-2..1e3", (-2, 1000.0)),
        ("eq:3", (3, 3)),
        ("eq:0.25", (0.25, 0.25)),
    ],
)
def test_number_ranges(raw: str, expected: tuple[Any, Any]) -> None:
    parsed = flt("indicator", "value", raw)
    assert (parsed.number_min, parsed.number_max) == expected


@pytest.mark.parametrize("raw", ["eq:abc", "eq:1_000", "eq:inf", "eq:nan", "range:5..1", "range:1"])
def test_malformed_numbers(raw: str) -> None:
    with pytest.raises(BadFilterError):
        flt("indicator", "value", raw)


def test_number_fields_take_any_finite_bound_as_a_float() -> None:
    # REAL column: an integer beyond 64 bits is compared as a float, never bound as int.
    parsed = flt("indicator", "value", "range:..1" + "0" * 30)
    assert parsed.number_max == 1e30 and isinstance(parsed.number_max, float)
    for raw in ("eq:1e999", "eq:" + "9" * 5000):  # beyond the float range: infinite
        with pytest.raises(BadFilterError):
            flt("indicator", "value", raw)


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("open_comments", "eq:9223372036854775807", (2**63 - 1, 2**63 - 1)),
        ("open_comments", "range:-9223372036854775808..", (-(2**63), None)),
        ("open_comments", "range:..000000000000000000000000000001", (None, 1)),
        ("comment_count", "range:1.5..1e30", (1.5, 1e30)),
    ],
)
def test_integer_field_bounds_within_64_bits(
    field: str, raw: str, expected: tuple[Any, Any]
) -> None:
    parsed = flt("project", field, raw)
    assert (parsed.number_min, parsed.number_max) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "eq:9223372036854775808",
        "range:-9223372036854775809..",
        "range:..99999999999999999999",
    ],
)
def test_integer_field_bounds_beyond_64_bits_are_bad_filters(raw: str) -> None:
    with pytest.raises(BadFilterError):
        flt("project", "open_comments", raw)


# --------------------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------------------


def sort_names(spec: Any, params: dict[str, str]) -> list[str]:
    query = parse_list_query(spec, params)
    return [("-" if key.descending else "") + key.name for key in query.sort]


def test_default_sort_per_type_and_for_the_trash() -> None:
    assert sort_names(PROJECT, {}) == ["paper_cluster", "name_en"]
    assert sort_names(EVENT, {"sort": "  "}) == ["-date"]
    assert sort_names(PROJECT, {"deleted": "only"}) == ["-deleted_at"]


def test_sort_with_directions_and_system_derived_virtual_fields() -> None:
    params = {"sort": "-launch,open_comments,-created_at"}
    assert sort_names(PROJECT, params) == ["-launch", "open_comments", "-created_at"]
    assert sort_names(SERVICE, {"sort": "project_id"}) == ["project_id"]


def test_relevance_needs_a_search_text() -> None:
    assert sort_names(DOCUMENT, {"q": "example", "sort": "relevance"}) == ["relevance"]
    with pytest.raises(BadSortError):
        parse_list_query(DOCUMENT, {"sort": "relevance"})


@pytest.mark.parametrize(
    "raw",
    [
        "name_en,name_uk,slug,status",  # more than three
        "name_en,-name_en",  # duplicate
        "description_en",  # not sortable
        "unknown",
        "seed_key",  # internal
        "name_en,,slug",  # empty item
        "-",
        "endpoint",
    ],
)
def test_bad_sorts(raw: str) -> None:
    spec = RELATION if raw == "endpoint" else PROJECT
    with pytest.raises(BadSortError):
        parse_list_query(spec, {"sort": raw})


# --------------------------------------------------------------------------------------
# Paging, deletion state and search
# --------------------------------------------------------------------------------------


def test_paging_defaults_and_limits() -> None:
    query = parse_list_query(PROJECT, {})
    assert (query.page, query.page_size, query.offset) == (1, 50, 0)
    query = parse_list_query(PROJECT, {"page": "3", "page_size": "500"})
    assert (query.page, query.page_size, query.offset) == (3, 500, 1000)


@pytest.mark.parametrize(
    "params",
    [{"page_size": "501"}, {"page_size": "0"}, {"page": "0"}, {"page": "x"}, {"page": "-1"}],
)
def test_invalid_paging_is_a_validation_error(params: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_list_query(PROJECT, params)
    assert set(caught.value.details or {}) <= {"page", "page_size"}


def test_deleted_modes() -> None:
    assert parse_list_query(PROJECT, {}).scope.deleted == "exclude"
    assert parse_list_query(PROJECT, {"deleted": "include"}).scope.deleted == "include"
    with pytest.raises(ValidationError):
        parse_list_query(PROJECT, {"deleted": "all"})


def test_search_text() -> None:
    scope = parse_list_query(PROJECT, {"q": "  "}).scope
    assert (scope.searching, scope.match) == (False, None)
    scope = parse_list_query(PROJECT, {"q": "Дія портал"}).scope
    assert scope.match == '"Дія"* AND "портал"*'
    scope = parse_list_query(PROJECT, {"q": " - . "}).scope
    assert scope.matches_nothing


def test_scope_without_drops_one_filter() -> None:
    scope = parse_list_query(PROJECT, {"f.status": "in:a", "f.name_en": "eq:x"}).scope
    assert set(scope.without("status").filters) == {"name_en"}
    assert isinstance(scope, Scope)


def test_unknown_parameters_are_ignored() -> None:
    query = parse_list_query(PROJECT, {"cols": "name_en", "utm_source": "x", "thread": "1"})
    assert query.scope.filters == {}
