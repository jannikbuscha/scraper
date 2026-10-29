"""Sorting of the list query (docs/API.md §4.2) on a shared synthetic catalog."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mdt.db.models import VocabularyTerm
from mdt.db.session import read_transaction
from mdt.domain.comments import create_comment
from mdt.domain.errors import BadSortError
from mdt.domain.query import list_entities
from mdt.domain.revisions import soft_delete
from tests.conftest import Db
from tests.helpers import ALICE, BOB, create_event, create_project, create_service
from tests.read_helpers import assert_consistent, create, create_document, open_copy, update

# slug → (name_en, name_uk, paper_cluster, policy_domains, in_paper_scope, launch)
PROJECTS: dict[str, tuple[Any, ...]] = {
    "s-zeta": ("Zeta", "Zeta", "cluster_b", ["domain_c", "domain_a"], True, "2010"),
    "s-alfa": ("alfa", "Альфа", "cluster_a", ["domain_a"], False, "2012-05"),
    "s-hora": (None, "Гора", None, ["domain_b", "domain_c"], False, None),
    "s-grunt": ("Grunt", "Ґрунт", "cluster_b", [], True, "2017-02"),
    "s-yeva": ("Yeva", "Єва", "cluster_a", ["domain_b"], False, "2016"),
    "s-ynei": (None, "Иней", None, [], False, None),
    "s-ihry": ("Ihry", "ігри", None, [], False, None),
    "s-yizhak": (None, "Їжак", None, [], False, None),
    "s-yod": ("Yod", "Йод", None, [], False, None),
    "s-english": ("Only English", None, None, [], False, None),
}


@dataclass
class Catalog:
    db: Db
    ids: dict[str, str]

    def order(self, entity_type: str, params: dict[str, str]) -> list[str]:
        with self.db.session() as session:
            result = list_entities(session, entity_type, {**params, "page_size": "500"})
        names = {entity_id: name for name, entity_id in self.ids.items()}
        return [names.get(item["id"], item["id"]) for item in result["items"]]


def build(session: Any) -> dict[str, str]:
    ids: dict[str, str] = {}
    for slug, (name_en, name_uk, cluster, domains, scope, launch) in PROJECTS.items():
        ids[slug] = create_project(
            session,
            slug=slug,
            name_en=name_en,
            name_uk=name_uk,
            paper_cluster=cluster,
            policy_domains=domains,
            in_paper_scope=scope,
        ).entity_id
        if launch:
            create_event(session, ids[slug], "launch", launch)
    # cluster_a sorts after cluster_b once its sort_order is changed (codes stay).
    with read_transaction(session):
        term_id = session.execute(
            select(VocabularyTerm.id).where(
                VocabularyTerm.vocabulary == "paper_cluster", VocabularyTerm.code == "cluster_a"
            )
        ).scalar_one()
    update(session, "vocabulary_term", term_id, sort_order=30)
    for _ in range(2):
        update(session, "project", ids["s-alfa"], notes=f"Edit {_}")
    ids["s-bob"] = create_project(session, BOB, slug="s-bob", name_en="By Bob").entity_id
    for count, slug in ((2, "s-hora"), (1, "s-ynei")):
        for index in range(count):
            create_comment(session, ids[slug], f"Open thread {index}", ALICE)

    # services: sorted by the label of their project
    for slug in ("s-alfa", "s-hora", "s-english"):
        ids[f"svc-{slug}"] = create_service(
            session, ids[slug], name_en=f"Service of {slug}"
        ).entity_id
    ids["svc-child"] = create_service(
        session, ids["s-alfa"], name_en="Child", parent_service_id=ids["svc-s-alfa"]
    ).entity_id

    # events: polymorphic subjects (announced) and partial dates (expansion)
    organization = create(session, "organization", name_en="Zulu org").entity_id
    component = create(session, "component", name_en="Middle component").entity_id
    for name, subject in (
        ("ev-project", ids["s-alfa"]),
        ("ev-service", ids["svc-s-alfa"]),
        ("ev-organization", organization),
        ("ev-component", component),
    ):
        ids[name] = create_event(session, subject, "announced").entity_id
    for name, value in (
        ("year", "2016"),
        ("month", "2016-01"),
        ("quarter", "2016-Q1"),
        ("day", "2016-01-15"),
        ("previous", "2015-Q4"),
        ("undated", None),
    ):
        ids[name] = create_event(session, component, "expansion", value).entity_id

    # documents for relevance
    ids["doc-strong"] = create_document(
        session, "Alpha alpha alpha", text="Alpha alpha alpha alpha."
    ).entity_id
    ids["doc-weak"] = create_document(
        session,
        "A long title that mentions alpha once among many other words",
        text=" ".join(["Filler words without the search term."] * 40) + " Alpha.",
    ).entity_id

    # trash: deleted in this order
    for slug in ("trash-first", "trash-second"):
        result = create_project(session, slug=slug, name_en=slug)
        soft_delete(session, "project", result.entity_id, ALICE, expected_version=1)
        ids[slug] = result.entity_id
    return ids


@pytest.fixture(scope="module")
def catalog(
    tmp_path_factory: pytest.TempPathFactory, template_db: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Catalog]:
    database = open_copy(tmp_path_factory, template_db, codebook_dir, seed_dir, "sorting")
    try:
        with database.session() as session:
            ids = build(session)
        yield Catalog(database, ids)
        assert_consistent(database)
    finally:
        database.engine.dispose()


NULL_NAME_EN = ["s-hora", "s-ynei", "s-yizhak"]


def by_id(catalog: Catalog, names: list[str]) -> list[str]:
    """Rows with equal sort keys are ordered by ID."""
    return sorted(names, key=lambda name: catalog.ids[name])


def test_ukrainian_alphabetical_order_latin_first_nulls_last(catalog: Catalog) -> None:
    expected = [
        "s-zeta",  # Zeta (Latin first)
        "s-alfa",  # Альфа
        "s-hora",  # Гора
        "s-grunt",  # Ґрунт (ґ after г)
        "s-yeva",  # Єва (є after е)
        "s-ynei",  # Иней
        "s-ihry",  # ігри (і after и, case-insensitive)
        "s-yizhak",  # Їжак
        "s-yod",  # Йод
    ]
    order = catalog.order("project", {"sort": "name_uk", "f.slug": "contains:s-"})
    assert order[: len(expected)] == expected
    assert set(order[len(expected) :]) == {"s-english", "s-bob"}  # NULL name_uk last
    order = catalog.order("project", {"sort": "-name_uk", "f.slug": "contains:s-"})
    assert order[: len(expected)] == list(reversed(expected))
    assert set(order[len(expected) :]) == {"s-english", "s-bob"}


def test_case_insensitive_text_sort_with_nulls_last_in_both_directions(catalog: Catalog) -> None:
    named = ["s-alfa", "s-bob", "s-grunt", "s-ihry", "s-english", "s-yeva", "s-yod", "s-zeta"]
    params = {"f.slug": "contains:s-"}
    assert catalog.order("project", {**params, "sort": "name_en"}) == named + by_id(
        catalog, NULL_NAME_EN
    )
    assert catalog.order("project", {**params, "sort": "-name_en"}) == list(
        reversed(named)
    ) + by_id(catalog, NULL_NAME_EN)


def test_vocabulary_sort_uses_sort_order_then_code(catalog: Catalog) -> None:
    # cluster_a has sort_order 30 here, cluster_b 20.
    params = {"f.paper_cluster": "empty:false", "sort": "paper_cluster,slug"}
    assert catalog.order("project", params) == ["s-grunt", "s-zeta", "s-alfa", "s-yeva"]
    params["sort"] = "-paper_cluster,slug"
    assert catalog.order("project", params) == ["s-alfa", "s-yeva", "s-grunt", "s-zeta"]


def test_vocabulary_nulls_last_in_both_directions(catalog: Catalog) -> None:
    for sort in ("paper_cluster,slug", "-paper_cluster,slug"):
        order = catalog.order("project", {"sort": sort, "f.slug": "contains:s-"})
        assert set(order[4:]) == {
            "s-hora",
            "s-ynei",
            "s-ihry",
            "s-yizhak",
            "s-yod",
            "s-english",
            "s-bob",
        }


def test_vocab_list_sorts_by_its_first_element(catalog: Catalog) -> None:
    params = {"f.policy_domains": "empty:false", "sort": "policy_domains,slug"}
    assert catalog.order("project", params) == ["s-alfa", "s-hora", "s-yeva", "s-zeta"]
    params["sort"] = "-policy_domains,slug"
    assert catalog.order("project", params) == ["s-zeta", "s-hora", "s-yeva", "s-alfa"]
    order = catalog.order("project", {"sort": "-policy_domains", "f.slug": "contains:s-"})
    assert order[:4] == ["s-zeta", *by_id(catalog, ["s-hora", "s-yeva"]), "s-alfa"]


def test_reference_sorts_by_the_target_label(catalog: Catalog) -> None:
    # Labels: "alfa" < "Only English" < "Гора" (name_uk, Cyrillic after Latin).
    params = {"f.parent_service_id": "empty:true"}
    expected = ["svc-s-alfa", "svc-s-english", "svc-s-hora"]
    assert catalog.order("service", {**params, "sort": "project_id"}) == expected
    assert catalog.order("service", {**params, "sort": "-project_id"}) == list(reversed(expected))


def test_nullable_reference_sorts_nulls_last(catalog: Catalog) -> None:
    for sort in ("parent_service_id", "-parent_service_id"):
        assert catalog.order("service", {"sort": sort})[0] == "svc-child"


def test_polymorphic_reference_uses_one_join_per_type(catalog: Catalog) -> None:
    params = {"f.event_type": "in:announced"}
    expected = ["ev-project", "ev-component", "ev-service", "ev-organization"]
    # alfa < Middle component < Service of s-alfa < Zulu org
    assert catalog.order("event", {**params, "sort": "subject_id"}) == expected
    assert catalog.order("event", {**params, "sort": "-subject_id"}) == list(reversed(expected))


def test_partial_dates_sort_by_start_then_end(catalog: Catalog) -> None:
    params = {"f.event_type": "in:expansion"}
    ascending = ["previous", "month", "quarter", "year", "day", "undated"]
    descending = ["day", "year", "quarter", "month", "previous", "undated"]
    assert catalog.order("event", {**params, "sort": "date"}) == ascending
    assert catalog.order("event", {**params, "sort": "-date"}) == descending
    # the default sort of events is -date
    assert catalog.order("event", params) == descending


def test_derived_launch_and_period_sorting(catalog: Catalog) -> None:
    params = {"f.launch": "empty:false"}
    assert catalog.order("project", {**params, "sort": "launch"}) == [
        "s-zeta",
        "s-alfa",
        "s-yeva",
        "s-grunt",
    ]
    assert catalog.order("project", {**params, "sort": "-launch"}) == [
        "s-grunt",
        "s-yeva",
        "s-alfa",
        "s-zeta",
    ]
    order = catalog.order("project", {"sort": "launch", "f.slug": "contains:s-"})
    assert order[4:] == by_id(catalog, order[4:])  # no launch: last, by ID
    # period by sort_order: pre_ministry, pre_invasion, full_scale_war, unknown
    order = catalog.order("project", {"sort": "period,slug", "f.slug": "contains:s-"})
    assert order[:4] == ["s-zeta", "s-alfa", "s-grunt", "s-bob"]


def test_virtual_count_and_bool_sorting(catalog: Catalog) -> None:
    order = catalog.order("project", {"sort": "-open_comments,slug"})
    assert order[:2] == ["s-hora", "s-ynei"]
    order = catalog.order("project", {"sort": "in_paper_scope,slug", "f.slug": "contains:s-"})
    assert order[-2:] == ["s-grunt", "s-zeta"]
    order = catalog.order("project", {"sort": "-in_paper_scope", "f.slug": "contains:s-"})
    assert order[:2] == by_id(catalog, ["s-grunt", "s-zeta"])


def test_system_columns_sort(catalog: Catalog) -> None:
    assert catalog.order("project", {"sort": "-version,slug"})[0] == "s-alfa"
    assert catalog.order("project", {"sort": "-created_by,slug"})[0] == "s-bob"
    # s-bob was created after the last edit of s-alfa
    assert catalog.order("project", {"sort": "-updated_at"})[:2] == ["s-bob", "s-alfa"]


def test_tie_breaker_is_the_id(catalog: Catalog) -> None:
    order = catalog.order("project", {"sort": "in_paper_scope", "f.in_paper_scope": "eq:false"})
    assert order == by_id(catalog, order)


def test_multi_sort_and_default_sort(catalog: Catalog) -> None:
    explicit = catalog.order("project", {"sort": "paper_cluster,name_en"})
    assert catalog.order("project", {}) == explicit
    assert explicit[:4] == ["s-grunt", "s-zeta", "s-alfa", "s-yeva"]


def test_trash_default_sort_is_newest_deletion_first(catalog: Catalog) -> None:
    assert catalog.order("project", {"deleted": "only"}) == ["trash-second", "trash-first"]
    assert catalog.order("project", {"deleted": "only", "sort": "deleted_at"}) == [
        "trash-first",
        "trash-second",
    ]


def test_relevance_sort_uses_bm25(catalog: Catalog) -> None:
    params = {"q": "alpha", "f.title": "contains:alpha"}
    assert catalog.order("document", {**params, "sort": "relevance"}) == [
        "doc-strong",
        "doc-weak",
    ]
    assert catalog.order("document", {**params, "sort": "-relevance"}) == [
        "doc-weak",
        "doc-strong",
    ]


def test_bad_sort_raises_before_querying(catalog: Catalog) -> None:
    with catalog.db.session() as session, pytest.raises(BadSortError):
        list_entities(session, "project", {"sort": "description_en"})
