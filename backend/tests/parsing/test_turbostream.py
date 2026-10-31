"""The turbo-stream decoder (parsing/turbostream.py, docs/COLLECTORS.md §7.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.turbostream import (
    decode,
    find_route,
    loader_data,
    stream_from_html,
)
from tests.parsing.helpers import FIXTURES, fixture_text

#: Every fixture that embeds a turbo-stream, with the keys its page entry must have.
LISTING_PAGES = {
    ("ministry_projects", "projects_page1.html"): "projects",
    ("ministry_projects", "projects_page2.html"): "projects",
    ("ministry_news", "news_list_page1.html"): "articles",
    ("ministry_news", "news_list_page366.html"): "articles",
    ("ministry_news", "documents_list_page1.html"): "documents",
    ("ministry_news", "documents_list_page106.html"): "documents",
}
DETAIL_PAGES = {
    ("ministry_projects", "project_brave1_technologies.html"): "project",
    ("ministry_projects", "project_diiatsyfrova_hromada_additional_rubric.html"): "project",
    ("ministry_projects", "project_virtual_assets_business.html"): "project",
    ("ministry_projects", "project_yevrointegraciya_progress.html"): "project",
    ("ministry_projects", "variant_yevrointegraciya_302.html"): "project",
    ("ministry_projects", "variant_regions_city_same_record.html"): "project",
    ("ministry_news", "news_article_2019.html"): "article",
    ("ministry_news", "news_article_2022.html"): "article",
    ("ministry_news", "news_article_2026.html"): "article",
    ("ministry_news", "news_article_en_2024.html"): "article",
    ("ministry_news", "news_article_redirect_2021.html"): "article",
    ("ministry_news", "document_page_content.html"): "document",
    ("ministry_news", "ministry_page.html"): "page",
}


def _routes(collector: str, name: str) -> dict[str, object]:
    return loader_data(fixture_text(collector, name))


@pytest.mark.parametrize(("page", "key"), sorted(LISTING_PAGES.items()))
def test_listing_pages_select_the_entry_with_pagination(page: tuple[str, str], key: str) -> None:
    route_id, data = find_route(_routes(*page), (key,), required=("pagination",))
    assert route_id != "root"
    assert isinstance(data["pagination"], dict)
    assert isinstance(data[key], list) and data[key]


@pytest.mark.parametrize(("page", "key"), sorted(DETAIL_PAGES.items()))
def test_detail_pages_select_the_entry_by_key(page: tuple[str, str], key: str) -> None:
    route_id, data = find_route(_routes(*page), ("project", "article", "document", "page"))
    assert route_id != "root"
    assert isinstance(data[key], dict)


@pytest.mark.parametrize("path", sorted((FIXTURES / "ministry_projects").glob("category_*.html")))
def test_rubric_listings_decode_and_select_by_keys(path: Path) -> None:
    routes = loader_data(path.read_text(encoding="utf-8"))
    _, data = find_route(routes, ("projects",), required=("pagination",))
    assert "rubric" in data


STREAM_PAGES = sorted(
    path
    for path in FIXTURES.glob("*/*.html")
    if "streamController.enqueue(" in path.read_text(encoding="utf-8")
)


@pytest.mark.parametrize("path", STREAM_PAGES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_every_turbo_stream_fixture_decodes(path: Path) -> None:
    routes = loader_data(path.read_text(encoding="utf-8"))
    assert "root" in routes


def test_the_turbo_stream_fixtures_include_remix_pages() -> None:
    folders = {path.parent.name for path in STREAM_PAGES}
    assert {"ministry_projects", "ministry_news", "digitalstate_catalog"} <= folders


def test_data_body_is_unwrapped_to_the_same_mapping_as_the_html_page() -> None:
    from_data = _routes("ministry_projects", "projects_data_turbostream.txt")
    from_html = _routes("ministry_projects", "projects_page1.html")
    assert set(from_data) == set(from_html)
    assert from_data == from_html


def test_the_html_page_holds_loader_data_and_root_is_skipped() -> None:
    routes = _routes("ministry_projects", "projects_page1.html")
    assert "root" in routes
    # A root entry with the wanted keys is never chosen.
    routes = {"root": {"project": {}}, **routes}
    with pytest.raises(ParseError, match="no loader entry"):
        find_route(routes, ("project",))


def test_an_error_page_has_no_page_entry() -> None:
    routes = _routes("ministry_projects", "legacy_e_residency_404.html")
    with pytest.raises(ParseError):
        find_route(routes, ("project", "projects"))


def test_a_page_without_a_stream_raises() -> None:
    with pytest.raises(ParseError, match="no turbo-stream"):
        stream_from_html(fixture_text("ministry_news", "microsite_2years_report.html"))


def _stream(values: list[object]) -> str:
    return json.dumps(values, ensure_ascii=False) + "\n"


def test_objects_arrays_shared_references_and_null() -> None:
    # Index 4 holds the number 7 itself: plain numbers are values, not references.
    stream = _stream([{"_1": 2, "_3": 4, "_5": -5}, "a", [6, 6], "b", 7, "c", "x"])
    assert decode(stream) == {"a": ["x", "x"], "b": 7, "c": None}


def test_undefined_omits_the_key_and_becomes_none_in_arrays() -> None:
    stream = _stream([{"_1": -7, "_2": 3}, "gone", "items", [-7, 4], "kept"])
    assert decode(stream) == {"items": [None, "kept"]}


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ([{"_1": -2}, "nan"], "unsupported turbo-stream constant -2"),
        ([{"_1": 2}, "when", ["D", 1]], "typed value"),
        ([{"_1": 0}, "self"], "circular reference"),
        ([{"_1": 9}, "missing"], "out of range"),
        ([{"x1": 1}, "bad"], "not a reference"),
        ([{"_1": 2}, 5, "value"], "does not name a string"),
        ([[True]], "not an integer"),
    ],
)
def test_unknown_constructs_raise(values: list[object], message: str) -> None:
    with pytest.raises(ParseError, match=message):
        decode(_stream(values))


def test_promise_lines_and_malformed_streams_raise() -> None:
    with pytest.raises(ParseError, match="further lines"):
        decode('[{"_1":2},"a","b"]\nP1:[3]\n')
    with pytest.raises(ParseError, match="not JSON"):
        decode("[{")
    with pytest.raises(ParseError, match="non-empty JSON array"):
        decode("[]")


def test_a_data_body_without_route_entries_raises() -> None:
    with pytest.raises(ParseError, match="neither loaderData"):
        loader_data(_stream([{"_1": 2}, "root", "not an entry"]))
    with pytest.raises(ParseError, match="root is not an object"):
        loader_data(_stream(["text"]))
    with pytest.raises(ParseError, match="loaderData is not an object"):
        loader_data(_stream([{"_1": 2}, "loaderData", "text"]))


def test_enqueued_chunks_are_concatenated_in_order() -> None:
    stream = _stream([{"_1": 2}, "loaderData", {"_3": 4}, "page.view", {"_5": 6}, "page", "x"])
    middle = len(stream) // 2
    html = (
        "<script>window.__reactRouterContext.streamController.enqueue("
        f"{json.dumps(stream[:middle])});</script>"
        "<script>window.__reactRouterContext.streamController.enqueue("
        f"{json.dumps(stream[middle:])});</script>"
    )
    assert loader_data(html) == {"page.view": {"page": "x"}}
