"""Normalisation per field type and limits (DATA_MODEL §1.2, §1.3)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.domain.errors import Problems, ValidationError
from mdt.domain.normalize import (
    INVALID,
    MAX_JSON_BYTES,
    ValueProblem,
    canonical_json,
    is_empty,
    normalize_note,
    normalize_value,
    unpaired_surrogate_problems,
    values_equal,
)
from mdt.domain.registry import ENTITY_TYPES, FieldSpec

PROJECT = ENTITY_TYPES["project"]
SERVICE = ENTITY_TYPES["service"]
DOCUMENT = ENTITY_TYPES["document"]
ORGANIZATION = ENTITY_TYPES["organization"]
VOCABULARY_TERM = ENTITY_TYPES["vocabulary_term"]


def normalized(spec: FieldSpec, value: Any) -> Any:
    problems = Problems()
    result = normalize_value(spec, value, problems)
    assert not problems, problems._items
    return result


def problems_of(spec: FieldSpec, value: Any) -> dict[str, list[str]]:
    problems = Problems()
    assert normalize_value(spec, value, problems) is INVALID
    with pytest.raises(ValidationError) as caught:
        problems.raise_if_any()
    assert caught.value.details is not None
    return caught.value.details


# --------------------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------------------


def test_string_is_nfc_trimmed_and_empty_becomes_null() -> None:
    name = PROJECT.field("name_en")
    assert normalized(name, "  Example\N{NO-BREAK SPACE}") == "Example"
    assert normalized(name, "e\N{COMBINING ACUTE ACCENT}") == "\N{LATIN SMALL LETTER E WITH ACUTE}"
    assert normalized(name, "   ") is None
    assert normalized(name, "") is None
    assert normalized(name, None) is None


@pytest.mark.parametrize("value", ["a\nb", "a\tb", "a\x00b", "a\x1bb"])
def test_string_refuses_control_characters(value: str) -> None:
    assert "name_en" in problems_of(PROJECT.field("name_en"), value)


def test_string_length_limit_and_type() -> None:
    name = PROJECT.field("name_en")
    assert normalized(name, "x" * 500) == "x" * 500
    assert problems_of(name, "x" * 501) == {"name_en": ["must be at most 500 characters"]}
    assert problems_of(name, 5) == {"name_en": ["must be a string"]}
    assert normalized(DOCUMENT.field("title"), "t" * 1000) == "t" * 1000
    assert "title" in problems_of(DOCUMENT.field("title"), "t" * 1001)


def test_messages_never_repeat_the_submitted_value() -> None:
    details = problems_of(PROJECT.field("slug"), "Secret Value")
    assert "Secret Value" not in str(details)


def test_text_normalises_line_breaks_and_keeps_tabs() -> None:
    notes = PROJECT.field("notes")
    assert normalized(notes, "\r\n line one\r\nline\ttwo\rthree \n") == "line one\nline\ttwo\nthree"
    assert normalized(notes, "\n\n") is None
    assert "notes" in problems_of(notes, "bell\x07")
    assert "notes" in problems_of(notes, "x" * 20_001)


def test_slug_pattern() -> None:
    slug = PROJECT.field("slug")
    assert normalized(slug, "example-1") == "example-1"
    for value in ("Example", "example--1", "-example", "example-", "exa_mple", "приклад"):
        assert "slug" in problems_of(slug, value)
    assert "slug" in problems_of(slug, "a" * 101)


def test_country_is_upper_cased_and_checked() -> None:
    country = ORGANIZATION.field("country")
    assert normalized(country, " xa ") == "XA"
    for value in ("XAX", "X1", "x"):
        assert "country" in problems_of(country, value)


def test_vocabulary_code_pattern() -> None:
    code = VOCABULARY_TERM.field("code")
    assert normalized(code, "example_code_1") == "example_code_1"
    assert "code" in problems_of(code, "Example-Code")


def test_bool_int_number() -> None:
    scope = PROJECT.field("in_paper_scope")
    assert normalized(scope, False) is False
    assert problems_of(scope, None) == {"in_paper_scope": ["must be true or false"]}
    assert "in_paper_scope" in problems_of(scope, 1)
    order = VOCABULARY_TERM.field("sort_order")
    assert normalized(order, 7) == 7
    assert normalized(order, None) is None
    assert "sort_order" in problems_of(order, True)
    assert "sort_order" in problems_of(order, 1.5)
    assert "sort_order" in problems_of(order, 2**63)
    value = ENTITY_TYPES["indicator"].field("value")
    assert normalized(value, 3) == 3.0
    assert normalized(value, 2.5) == 2.5
    for bad in (float("nan"), float("inf"), "3", True):
        assert "value" in problems_of(value, bad)
    # a JSON integer beyond the float range is not a finite number (float() overflows)
    assert problems_of(value, 10**400) == {"value": ["must be a finite number"]}
    assert normalized(value, 10**300) == 1e300


SURROGATE = "\ud800"


def test_unpaired_surrogates_are_refused_on_every_channel() -> None:
    # The JSON body check refuses them first over HTTP; normalisation refuses them for
    # the seed, imports and collectors too.
    assert "name_en" in problems_of(PROJECT.field("name_en"), f"a{SURROGATE}b")
    assert "notes" in problems_of(PROJECT.field("notes"), f"line{SURROGATE}")
    assert "official_urls[0]" in problems_of(
        PROJECT.field("official_urls"), [f"https://example.org/{SURROGATE}"]
    )
    assert "aliases[0].text" in problems_of(PROJECT.field("aliases"), [{"text": SURROGATE}])
    attributes = VOCABULARY_TERM.field("attributes")
    assert "attributes" in problems_of(attributes, {"k": f"v{SURROGATE}"})
    assert "attributes" in problems_of(attributes, {f"k{SURROGATE}": "v"})
    links = DOCUMENT.field("links")
    link = {
        "subject_id": "prj_01JBX3ABCDEFGHJKMNPQRSTVWX",
        "state": "suggested",
        "matched_aliases": [f"x{SURROGATE}"],
    }
    assert "links[0].matched_aliases" in problems_of(links, [link])
    with pytest.raises(ValueProblem):
        normalize_note(f"note {SURROGATE}")
    # a surrogate pair written as one character is ordinary text
    assert normalized(PROJECT.field("name_en"), "Smile \U0001f600") == "Smile \U0001f600"


def test_unpaired_surrogate_problems_name_every_path() -> None:
    body = {
        "data": {"name_en": f"a{SURROGATE}", "aliases": [{"text": "ok"}, {"text": SURROGATE}]},
        "items": [{"id": f"x{SURROGATE}"}],
        "set": {f"k{SURROGATE}": "v"},
        "fine": ["ok", 1, None, True],
    }
    problems = unpaired_surrogate_problems(body)
    assert sorted(problems) == ["data.aliases[1].text", "data.name_en", "items[0].id", "set"]
    assert SURROGATE not in str(problems)
    assert unpaired_surrogate_problems({"a": ["b", {"c": "d"}]}) == {}
    assert list(unpaired_surrogate_problems(SURROGATE)) == ["body"]


def test_ref_checks_the_prefix() -> None:
    project_id = SERVICE.field("project_id")
    good = "prj_01JBX3ABCDEFGHJKMNPQRSTVWX"
    assert normalized(project_id, f" {good} ") == good
    assert normalized(project_id, "") is None
    assert "project_id" in problems_of(project_id, "svc_01JBX3ABCDEFGHJKMNPQRSTVWX")
    assert "project_id" in problems_of(project_id, "prj_lowercase")
    assert "project_id" in problems_of(project_id, "xyz_01JBX3ABCDEFGHJKMNPQRSTVWX")
    assert "project_id" in problems_of(project_id, 12)


def test_partial_date_and_datetime() -> None:
    date_field = ENTITY_TYPES["event"].field("date")
    assert normalized(date_field, " 2020-Q3 ") == "2020-Q3"
    assert normalized(date_field, "") is None
    assert "date" in problems_of(date_field, "2020-q3")
    assert "date" in problems_of(date_field, "2020-02-30")
    retrieved = DOCUMENT.field("retrieved_at")
    assert normalized(retrieved, "2026-10-28T19:00:00+02:00") == "2026-10-28T17:00:00.000000Z"
    assert "retrieved_at" in problems_of(retrieved, "2026-10-28T17:00:00")


def test_url_field() -> None:
    url = DOCUMENT.field("url")
    assert normalized(url, " HTTPS://example.org/a ") == "https://example.org/a"
    assert normalized(url, "  ") is None
    assert "url" in problems_of(url, "javascript:alert(1)")
    assert "url" in problems_of(url, "https://user@example.org/")


# --------------------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------------------


def test_null_list_becomes_empty_list() -> None:
    assert normalized(PROJECT.field("policy_domains"), None) == []
    assert normalized(PROJECT.field("official_urls"), None) == []
    assert normalized(PROJECT.field("aliases"), None) == []


def test_list_elements_are_normalised_deduplicated_and_keep_their_order() -> None:
    domains = PROJECT.field("policy_domains")
    assert normalized(domains, ["domain_b", " domain_a ", "", None, "domain_b"]) == [
        "domain_b",
        "domain_a",
    ]
    urls = PROJECT.field("official_urls")
    assert normalized(urls, ["https://example.org/b", "HTTPS://example.org/b", " "]) == [
        "https://example.org/b"
    ]


def test_list_element_errors_name_the_index() -> None:
    urls = PROJECT.field("official_urls")
    assert problems_of(urls, ["https://example.org", "ftp://example.org"]) == {
        "official_urls[1]": ["the scheme must be http or https"]
    }
    assert problems_of(urls, "https://example.org") == {"official_urls": ["must be a list"]}


def test_list_limit_is_200_items() -> None:
    audiences = SERVICE.field("source_audiences")
    assert len(normalized(audiences, [f"audience {i}" for i in range(200)])) == 200
    assert problems_of(audiences, [f"audience {i}" for i in range(201)]) == {
        "source_audiences": ["must have at most 200 items"]
    }


def test_aliases_get_defaults_and_are_deduplicated_by_text_and_language() -> None:
    aliases = PROJECT.field("aliases")
    result = normalized(
        aliases,
        [
            {"text": " Example ", "lang": "en"},
            {"text": "Example", "lang": "en", "kind": "abbreviation"},
            {"text": "Example", "lang": "uk", "exclude_patterns": ["a phrase", "", "a phrase"]},
            {"text": "", "lang": "en"},
        ],
    )
    assert result == [
        {
            "text": "Example",
            "lang": "en",
            "case_sensitive": True,
            "kind": "name",
            "exclude_patterns": [],
        },
        {
            "text": "Example",
            "lang": "uk",
            "case_sensitive": True,
            "kind": "name",
            "exclude_patterns": ["a phrase"],
        },
    ]


def test_alias_errors() -> None:
    aliases = PROJECT.field("aliases")
    details = problems_of(
        aliases,
        [
            "Example",
            {"text": "Example", "kind": "nickname", "case_sensitive": "yes", "extra": 1},
            {"text": "Example", "exclude_patterns": ["x" * 201]},
            {"text": "Example", "exclude_patterns": [f"phrase {i}" for i in range(21)]},
        ],
    )
    assert details["aliases[0]"] == ["must be an object"]
    assert "aliases[1].kind" in details
    assert "aliases[1].case_sensitive" in details
    assert details["aliases[1].extra"] == ["unknown key"]
    assert "aliases[2].exclude_patterns[0]" in details
    assert details["aliases[3].exclude_patterns"] == ["must have at most 20 items"]
    assert "aliases" in problems_of(aliases, [{"text": f"Alias {i}"} for i in range(101)])


def test_doc_links_are_sorted_and_unique_per_subject() -> None:
    links = DOCUMENT.field("links")
    first, second = "prj_01JBX3ABCDEFGHJKMNPQRSTVWZ", "prj_01JBX3ABCDEFGHJKMNPQRSTVWX"
    result = normalized(
        links,
        [
            {"subject_id": first, "state": "suggested"},
            {"subject_id": second, "state": "confirmed", "origin": "manual", "match_count": 3},
        ],
    )
    assert [link["subject_id"] for link in result] == [second, first]
    assert "links" in problems_of(
        links,
        [{"subject_id": first, "state": "suggested"}, {"subject_id": first, "state": "rejected"}],
    )
    details = problems_of(links, [{"subject_id": first, "state": "maybe", "origin": "robot"}])
    assert set(details) == {"links[0].state", "links[0].origin"}


# --------------------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------------------


def test_json_limits() -> None:
    attributes = VOCABULARY_TERM.field("attributes")
    nested: Any = "leaf"
    for _ in range(10):
        nested = [nested]
    assert normalized(attributes, nested) == nested
    assert "attributes" in problems_of(attributes, [nested])
    big = {"text": "x" * MAX_JSON_BYTES}
    assert "attributes" in problems_of(attributes, big)
    assert "attributes" in problems_of(attributes, {"x": float("nan")})


def test_json_is_copied_not_shared() -> None:
    attributes = VOCABULARY_TERM.field("attributes")
    value = {"flags": [1, 2]}
    result = normalized(attributes, value)
    result["flags"].append(3)
    assert value == {"flags": [1, 2]}


def test_source_categories_urls_follow_the_url_rule() -> None:
    categories = SERVICE.field("source_categories")
    assert normalized(
        categories,
        [{"source": " Example source ", "label": "Section", "url": "HTTPS://example.org"}],
    ) == [{"source": "Example source", "label": "Section", "url": "https://example.org"}]
    assert "source_categories[0]" in problems_of(
        categories, [{"source": "x", "label": "y", "url": "https://user@example.org"}]
    )
    assert "source_categories[0]" in problems_of(categories, [{"unknown": 1}])
    assert "source_categories" in problems_of(categories, {"source": "x"})


# --------------------------------------------------------------------------------------
# Comparison helpers and notes
# --------------------------------------------------------------------------------------


def test_empty_means_null_or_empty_list() -> None:
    assert is_empty(None)
    assert is_empty([])
    assert not is_empty(False)
    assert not is_empty(0)
    assert not is_empty("")  # strings are normalised to None before this check


def test_values_equal() -> None:
    assert values_equal(PROJECT.field("policy_domains"), None, [])
    assert not values_equal(PROJECT.field("policy_domains"), ["a", "b"], ["b", "a"])
    assert not values_equal(PROJECT.field("in_paper_scope"), False, None)
    assert not values_equal(PROJECT.field("in_paper_scope"), False, 0)
    assert values_equal(VOCABULARY_TERM.field("attributes"), {"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert canonical_json({"b": "Приклад", "a": 1}) == '{"a":1,"b":"Приклад"}'


def test_note_rules() -> None:
    assert normalize_note(None) is None
    assert normalize_note("  a note \r\n") == "a note"
    assert normalize_note("n" * 2000) == "n" * 2000
    with pytest.raises(ValueError):
        normalize_note("n" * 2001)
