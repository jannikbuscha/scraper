"""Facets (docs/API.md §3.2), statistics and vocabulary usage counts (§3.1)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mdt.domain.comments import create_comment, resolve_comment
from mdt.domain.errors import BadFilterError, NotFoundError
from mdt.domain.query import entity_stats, facet_values, vocabulary_listing
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import ALICE, create_event, create_project, create_service
from tests.read_helpers import (
    assert_consistent,
    create,
    create_document,
    open_copy,
    term_id,
    update,
)


@dataclass
class Catalog:
    db: Db
    ids: dict[str, str]

    def facets(self, entity_type: str, **params: str) -> dict[str, Any]:
        resolved = {
            (f"f.{key[2:]}" if key.startswith("f_") else key): value
            for key, value in params.items()
        }
        with self.db.session() as session:
            return facet_values(session, entity_type, resolved)

    def counts(self, entity_type: str, **params: str) -> list[tuple[str, int]]:
        names = {entity_id: name for name, entity_id in self.ids.items()}
        result = self.facets(entity_type, **params)
        return [(names.get(v["value"], v["value"]), v["count"]) for v in result["values"]]


def build(session: Any) -> dict[str, str]:
    ids: dict[str, str] = {}
    projects = {
        "FA": ("Facet alpha", "active", "cluster_a", ["domain_a", "domain_b"], True),
        "FB": ("Facet beta", "active", "cluster_b", ["domain_b"], False),
        "FC": ("Facet gamma", None, None, [], False),
        "FE": ("Facet epsilon", "planned", "cluster_b", ["domain_c"], False),
        "FD": ("Facet deleted", "planned", "cluster_a", ["domain_a"], False),
    }
    for name, (label, status, cluster, domains, scope) in projects.items():
        ids[name] = create_project(
            session,
            name_en=label,
            status=status,
            paper_cluster=cluster,
            policy_domains=domains,
            in_paper_scope=scope,
        ).entity_id
    soft_delete(session, "project", ids["FD"], ALICE, expected_version=1)
    apply_change(
        session,
        "project",
        ids["FA"],
        {"verification_status": "verified"},
        ALICE,
        expected_version=1,
        note="Checked against the example source.",
    )
    create_event(session, ids["FA"], "launch", "2012")

    ids["SA"] = create_service(session, ids["FA"], name_en="Service A").entity_id
    ids["SB"] = create_service(
        session, ids["FA"], name_en="Service B", parent_service_id=ids["SA"]
    ).entity_id
    ids["SC"] = create_service(session, ids["FB"], name_en="Service C").entity_id

    def link(subject: str, state: str) -> dict[str, str]:
        return {"subject_id": ids[subject], "state": state}

    ids["DA"] = create_document(
        session, "Doc A", links=[link("FA", "confirmed"), link("SC", "suggested")]
    ).entity_id
    ids["DB"] = create_document(session, "Doc B", links=[link("FA", "rejected")]).entity_id
    ids["DC"] = create_document(session, "Doc C").entity_id
    ids["DD"] = create_document(session, "Doc D", links=[link("FB", "confirmed")]).entity_id

    create(session, "relation", from_id=ids["FA"], to_id=ids["SC"], relation_type="relates_a")
    create(session, "relation", from_id=ids["FB"], to_id=ids["FA"], relation_type="relates_b")

    # domain_b is deactivated after use; cluster_b moves before cluster_a.
    update(session, "vocabulary_term", term_id(session, "policy_domain", "domain_b"), active=False)
    update(session, "vocabulary_term", term_id(session, "paper_cluster", "cluster_b"), sort_order=5)

    ids["T_ACTIVE"] = term_id(session, "status", "active")
    create_comment(session, ids["T_ACTIVE"], "Is this definition precise?", ALICE)
    create_comment(session, ids["FA"], "Open thread", ALICE)
    resolved = create_comment(session, ids["FB"], "Resolved thread", ALICE)
    resolve_comment(session, resolved.entity_id, ALICE, expected_version=1)
    return ids


@pytest.fixture(scope="module")
def catalog(
    tmp_path_factory: pytest.TempPathFactory, template_db: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Catalog]:
    database = open_copy(tmp_path_factory, template_db, codebook_dir, seed_dir, "facets")
    try:
        with database.session() as session:
            ids = build(session)
        yield Catalog(database, ids)
        assert_consistent(database)
    finally:
        database.engine.dispose()


# --------------------------------------------------------------------------------------
# Vocabulary facets
# --------------------------------------------------------------------------------------


def test_vocab_facet_counts_labels_zero_counts_and_empty_count(catalog: Catalog) -> None:
    result = catalog.facets("project", field="status")
    assert result["field"] == "status"
    assert result["values"] == [
        {"value": "active", "label": "Example active", "count": 2},
        {"value": "planned", "label": "Example planned", "count": 1},
    ]  # the inactive term "retired" has no rows and is left out
    assert result["empty_count"] == 1


def test_facet_ignores_its_own_filter_but_applies_the_others(catalog: Catalog) -> None:
    assert catalog.counts("project", field="status", f_status="in:active") == [
        ("active", 2),
        ("planned", 1),
    ]
    filtered = catalog.facets("project", field="status", f_paper_cluster="in:cluster_b")
    assert [(v["value"], v["count"]) for v in filtered["values"]] == [("active", 1), ("planned", 1)]
    assert filtered["empty_count"] == 0


def test_facet_applies_search_and_deletion_state(catalog: Catalog) -> None:
    assert catalog.counts("project", field="status", q="alpha") == [("active", 1), ("planned", 0)]
    assert catalog.counts("project", field="status", deleted="include") == [
        ("active", 2),
        ("planned", 2),
    ]
    assert catalog.counts("project", field="status", q="- .") == [("active", 0), ("planned", 0)]


def test_vocab_list_facet_keeps_used_inactive_terms_in_sort_order(catalog: Catalog) -> None:
    result = catalog.facets("project", field="policy_domains")
    assert [(v["value"], v["count"]) for v in result["values"]] == [
        ("domain_a", 1),
        ("domain_b", 2),  # inactive but in use
        ("domain_c", 1),
    ]  # domain_old: inactive and unused
    assert result["empty_count"] == 1


def test_vocab_facet_follows_sort_order_not_code(catalog: Catalog) -> None:
    result = catalog.facets("project", field="paper_cluster")
    assert [(v["value"], v["count"]) for v in result["values"]] == [
        ("cluster_b", 2),
        ("cluster_a", 1),
    ]
    assert result["empty_count"] == 1


def test_derived_vocab_facet(catalog: Catalog) -> None:
    result = catalog.facets("project", field="period")
    assert [(v["value"], v["count"]) for v in result["values"]] == [
        ("pre_ministry", 0),
        ("pre_invasion", 1),
        ("full_scale_war", 0),
        ("unknown", 3),
    ]
    assert result["empty_count"] == 0


# --------------------------------------------------------------------------------------
# Boolean and reference facets
# --------------------------------------------------------------------------------------


def test_bool_facets(catalog: Catalog) -> None:
    result = catalog.facets("project", field="in_paper_scope")
    assert result["values"] == [
        {"value": "true", "label": "Yes", "count": 1},
        {"value": "false", "label": "No", "count": 3},
    ]
    assert catalog.counts("service", field="project_in_paper_scope") == [("true", 2), ("false", 1)]


def test_reference_facets_are_labelled_and_ordered_by_count(catalog: Catalog) -> None:
    result = catalog.facets("service", field="project_id")
    assert result["values"] == [
        {"value": catalog.ids["FA"], "label": "Facet alpha", "count": 2},
        {"value": catalog.ids["FB"], "label": "Facet beta", "count": 1},
    ]
    parents = catalog.facets("service", field="parent_service_id")
    assert [(v["label"], v["count"]) for v in parents["values"]] == [("Service A", 1)]
    assert parents["empty_count"] == 2


def test_link_facet_counts_suggested_and_confirmed_links(catalog: Catalog) -> None:
    result = catalog.facets("document", field="links")
    assert sorted(catalog.counts("document", field="links")) == [("FA", 1), ("FB", 1), ("SC", 1)]
    assert result["empty_count"] == 1  # Doc C; Doc B has a (rejected) link


def test_endpoint_facet_counts_both_ends(catalog: Catalog) -> None:
    assert catalog.counts("relation", field="endpoint")[0] == ("FA", 2)
    assert sorted(catalog.counts("relation", field="endpoint")[1:]) == [("FB", 1), ("SC", 1)]


@pytest.mark.parametrize(
    "params",
    [{}, {"field": "name_en"}, {"field": "unknown"}, {"field": "launch"}, {"field": "seed_key"}],
)
def test_facets_need_a_multiselect_bool_or_ref_field(
    catalog: Catalog, params: dict[str, str]
) -> None:
    with catalog.db.session() as session, pytest.raises(BadFilterError):
        facet_values(session, "project", params)


def test_facets_of_unknown_types_are_not_found(catalog: Catalog) -> None:
    with catalog.db.session() as session, pytest.raises(NotFoundError):
        facet_values(session, "comment", {"field": "status"})


# --------------------------------------------------------------------------------------
# Statistics and vocabulary usage
# --------------------------------------------------------------------------------------


def test_entity_stats(catalog: Catalog) -> None:
    with catalog.db.session() as session:
        stats = entity_stats(session)
    assert stats["entities"]["project"] == {"total": 4, "unverified": 3, "deleted": 1}
    assert stats["entities"]["service"] == {"total": 3, "unverified": 3, "deleted": 0}
    assert stats["entities"]["organization"]["total"] == 1  # the focal organisation
    assert "comment" not in stats["entities"]
    assert stats["open_comments"] == 2


def test_vocabulary_listing_with_usage_counts_and_open_comments(catalog: Catalog) -> None:
    with catalog.db.session() as session:
        listing = vocabulary_listing(session)
    vocabularies = {vocabulary["name"]: vocabulary for vocabulary in listing["vocabularies"]}
    assert list(vocabularies) == sorted(vocabularies)
    status = {term["code"]: term for term in vocabularies["status"]["terms"]}
    assert status["active"]["usage_count"] == 2
    assert status["planned"]["usage_count"] == 1  # the deleted project does not count
    assert status["retired"]["usage_count"] == 0
    assert status["active"]["open_comments"] == 1
    assert status["active"]["attributes"] == {}
    domains = {term["code"]: term for term in vocabularies["policy_domain"]["terms"]}
    assert (domains["domain_b"]["usage_count"], domains["domain_b"]["active"]) == (2, False)
    periods = {term["code"]: term["usage_count"] for term in vocabularies["period"]["terms"]}
    assert periods == {"pre_ministry": 0, "pre_invasion": 1, "full_scale_war": 0, "unknown": 6}
    clusters = [term["code"] for term in vocabularies["paper_cluster"]["terms"]]
    assert clusters == ["cluster_b", "cluster_a"]
    event_types = {term["code"]: term for term in vocabularies["event_type"]["terms"]}
    assert event_types["launch"]["attributes"]["fixed"] is True
    assert set(status["active"]) == {
        "id",
        "code",
        "label_en",
        "label_uk",
        "definition",
        "include_note",
        "exclude_note",
        "examples",
        "sort_order",
        "active",
        "replaced_by",
        "attributes",
        "version",
        "usage_count",
        "open_comments",
    }
    assert vocabularies["status"]["multi"] is False
    assert vocabularies["channel"]["multi"] is True
    assert vocabularies["period"]["fixed_codes"] is True
