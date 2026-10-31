"""List endpoint behaviour (docs/API.md §3.2, §4.3): paging, deletion state, full-text
search with snippets, and a fixed number of SQL statements per page (no N+1)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mdt.domain.comments import create_comment
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.query import list_entities
from mdt.domain.revisions import soft_delete
from tests.conftest import Db
from tests.helpers import USER, create_event, create_project, create_service
from tests.read_helpers import (
    assert_consistent,
    count_statements,
    create,
    create_document,
    ids_of,
    open_copy,
)

PAGE_ITEMS = 50


@dataclass
class Catalog:
    db: Db
    projects: list[str]
    documents: list[str]


@pytest.fixture(scope="module")
def catalog(
    tmp_path_factory: pytest.TempPathFactory, template_db: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Catalog]:
    database = open_copy(tmp_path_factory, template_db, codebook_dir, seed_dir, "listing")
    projects: list[str] = []
    documents: list[str] = []
    try:
        with database.session() as session:
            for index in range(PAGE_ITEMS):
                project = create_project(session, name_en=f"Bulk project {index:02d}")
                projects.append(project.entity_id)
                create_event(session, project.entity_id, "launch", f"20{10 + index % 9}")
                create_comment(session, project.entity_id, f"Note {index}", USER)
                service = create_service(session, project.entity_id, name_en=f"Bulk svc {index}")
                create_event(session, service.entity_id, "expansion", "2016-05")
                documents.append(
                    create_document(
                        session,
                        f"Bulk document {index}",
                        text=f"Bulk text number {index} about the example portal.",
                        links=[{"subject_id": project.entity_id, "state": "confirmed"}],
                    ).entity_id
                )
        yield Catalog(database, projects, documents)
        assert_consistent(database)
    finally:
        database.engine.dispose()


# --------------------------------------------------------------------------------------
# Paging
# --------------------------------------------------------------------------------------


def test_paging(catalog: Catalog) -> None:
    params = {"f.name_en": "contains:bulk project", "sort": "name_en", "page_size": "20"}
    with catalog.db.session() as session:
        pages = [
            list_entities(session, "project", {**params, "page": str(page)})
            for page in (1, 2, 3, 4)
        ]
    assert [len(page["items"]) for page in pages] == [20, 20, 10, 0]
    assert {page["total"] for page in pages} == {PAGE_ITEMS}
    assert [(page["page"], page["page_size"]) for page in pages[:2]] == [(1, 20), (2, 20)]
    seen = [entity_id for page in pages for entity_id in ids_of(page)]
    assert seen == catalog.projects  # names sort like creation order here, no duplicates


def test_page_size_limit(catalog: Catalog) -> None:
    with catalog.db.session() as session:
        result = list_entities(session, "project", {"page_size": "500"})
        assert len(result["items"]) == PAGE_ITEMS
        with pytest.raises(ValidationError):
            list_entities(session, "project", {"page_size": "501"})


def test_unknown_types_and_comments_are_not_listed(catalog: Catalog) -> None:
    with catalog.db.session() as session:
        for entity_type in ("unknown", "comment"):
            with pytest.raises(NotFoundError):
                list_entities(session, entity_type, {})


# --------------------------------------------------------------------------------------
# No N+1: the number of statements does not depend on the page size
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_type", "params"),
    [
        ("project", {"sort": "name_en"}),
        ("service", {"sort": "project_id"}),
        ("event", {"sort": "subject_id"}),
        ("document", {"q": "portal", "sort": "relevance"}),
        ("document", {"f.links": "empty:false"}),
    ],
)
def test_statement_count_is_independent_of_page_size(
    catalog: Catalog, entity_type: str, params: dict[str, str]
) -> None:
    counts = []
    for page_size in (5, PAGE_ITEMS):
        with catalog.db.session() as session, count_statements(catalog.db.engine) as statements:
            result = list_entities(session, entity_type, {**params, "page_size": str(page_size)})
        assert len(result["items"]) == min(page_size, result["total"])
        counts.append(len(statements))
    assert counts[0] == counts[1]
    assert counts[1] <= 12


def test_fifty_project_items_with_refs_and_counts(catalog: Catalog) -> None:
    with catalog.db.session() as session, count_statements(catalog.db.engine) as statements:
        result = list_entities(session, "project", {"page_size": str(PAGE_ITEMS)})
    assert len(result["items"]) == PAGE_ITEMS
    for item in result["items"]:
        assert item["virtual"] == {"open_comments": 1, "comment_count": 1, "open_proposals": 0}
        assert item["refs"]["derived.launch_event_id"]["type"] == "event"
        assert item["label"].startswith("Bulk project")
    assert len(statements) <= 12


# --------------------------------------------------------------------------------------
# Deletion state
# --------------------------------------------------------------------------------------


def test_deleted_modes(db: Db) -> None:
    with db.session() as session:
        live = create(session, "component", name_en="Live component").entity_id
        gone = create(session, "component", name_en="Deleted component").entity_id
        soft_delete(session, "component", gone, USER)
        assert ids_of(list_entities(session, "component", {})) == [live]
        assert ids_of(list_entities(session, "component", {"deleted": "only"})) == [gone]
        result = list_entities(session, "component", {"deleted": "include", "sort": "name_en"})
        assert ids_of(result) == [gone, live]
        assert result["items"][0]["deleted_at"] is not None
        assert result["items"][0]["deleted_by"] == USER.name


# --------------------------------------------------------------------------------------
# Full-text search
# --------------------------------------------------------------------------------------


def search(session: Any, entity_type: str, q: str, **params: str) -> list[str]:
    return ids_of(list_entities(session, entity_type, {"q": q, **params}))


def test_search_cyrillic_prefixes_case_and_apostrophes(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session,
            name_en=None,
            name_uk="Цифрова громада",
            description_uk="Послуга з\u2019явилася у застосунку.",
        ).entity_id
        create_project(session, name_en="Unrelated example")
        assert search(session, "project", "цифр") == [project]
        assert search(session, "project", "ГРОМ") == [project]
        assert search(session, "project", "з\u02bcявилася") == [project]
        assert search(session, "project", "з'явилася") == [project]
        assert search(session, "project", '"цифрова громада"') == [project]
        assert search(session, "project", "цифрова unrelated") == []


def test_search_combines_with_filters_and_blank_queries(db: Db) -> None:
    with db.session() as session:
        alpha = create_project(session, name_en="Search alpha", status="active").entity_id
        create_project(session, name_en="Search beta", status="planned")
        assert search(session, "project", "search", **{"f.status": "in:active"}) == [alpha]
        assert len(search(session, "project", "   ")) == 2  # blank q: no search
        result = list_entities(session, "project", {"q": "- – ."})
        assert (result["total"], result["items"]) == (0, [])


def test_deleted_entities_stay_searchable(db: Db) -> None:
    with db.session() as session:
        gone = create(session, "component", name_en="Searchable component").entity_id
        soft_delete(session, "component", gone, USER)
        assert search(session, "component", "searchable") == []
        assert search(session, "component", "searchable", deleted="only") == [gone]
        assert search(session, "component", "searchable", deleted="include") == [gone]


def test_document_search_matches_metadata_or_full_text_with_snippets(db: Db) -> None:
    with db.session() as session:
        by_text = create_document(
            session,
            "Annual overview",
            text="Мінцифри «запустили» нову послугу для громад. Інший текст.",
        ).entity_id
        by_metadata = create_document(
            session, "Quarterly note", publisher="Запуск Example Publisher"
        ).entity_id
        create_document(session, "Unrelated", text="Nothing relevant here.")
        # "запус" is a prefix of both "запустили" (text) and "Запуск" (publisher)
        result = list_entities(session, "document", {"q": "запус", "sort": "title"})
        assert ids_of(result) == [by_text, by_metadata]
        snippets = {item["id"]: item["search_snippet"] for item in result["items"]}
        text_segments = snippets[by_text]
        assert {"text": "запустили", "hit": True} in text_segments
        assert "«" in "".join(segment["text"] for segment in text_segments)
        assert all(set(segment) == {"text", "hit"} for segment in text_segments)
        assert "\ue000" not in "".join(segment["text"] for segment in text_segments)
        meta_segments = snippets[by_metadata]
        assert any(segment["hit"] and segment["text"] == "Запуск" for segment in meta_segments)
        # without q there is no snippet; other types never get one
        assert list_entities(session, "document", {})["items"][0]["search_snippet"] is None
        create_project(session, name_en="Запуск project")
        project_items = list_entities(session, "project", {"q": "запус"})["items"]
        assert [item["search_snippet"] for item in project_items] == [None]
