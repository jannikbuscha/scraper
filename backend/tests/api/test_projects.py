"""Definition of Done 2 over HTTP: the 19 projects of the paper and European Integration
are listed and can be filtered and sorted by every vocabulary field (and sorted by every
sortable field). Expected values are derived from ``seed/projects.yaml`` and the codebook;
records that tests add are synthetic."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

import pytest

from mdt.domain.seed import load_seed_file
from mdt.domain.text import sortkey
from mdt.domain.vocab import load_parameters
from tests.api.conftest import REAL_CODEBOOK, REAL_SEED
from tests.api.helpers import ApiClient, error_of

SYSTEM_KEYS = ("created_at", "updated_at", "deleted_at", "created_by", "updated_by", "deleted_by")


def seed_projects() -> list[dict[str, Any]]:
    return load_seed_file(REAL_SEED / "projects.yaml").sections["project"]


def project_fields(client: ApiClient) -> dict[str, dict[str, Any]]:
    meta = client.ok(client.get("/api/meta"))
    return {field["name"]: field for field in meta["entity_types"]["project"]["fields"]}


def all_projects(client: ApiClient, **params: Any) -> list[dict[str, Any]]:
    page = client.list("project", page_size=500, **params)
    assert page["total"] == len(page["items"])
    return list(page["items"])


def first_active_code(client: ApiClient, vocabulary: str) -> str:
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    terms = next(v["terms"] for v in listing if v["name"] == vocabulary)
    return str(next(term["code"] for term in terms if term["active"]))


# --------------------------------------------------------------------------------------
# The seeded projects
# --------------------------------------------------------------------------------------


def test_the_seeded_projects_are_listed(client: ApiClient) -> None:
    page = client.list("project")
    expected = {project["slug"]: project for project in seed_projects()}
    assert page["total"] == len(expected) == 20
    assert (page["page"], page["page_size"]) == (1, 50)
    items = {item["fields"]["slug"]: item for item in page["items"]}
    assert set(items) == set(expected)
    outside = [slug for slug, project in expected.items() if not project["in_paper_scope"]]
    assert outside == ["european-integration"]
    for slug, project in expected.items():
        item = items[slug]
        assert item["type"] == "project" and item["version"] == 1
        assert item["fields"]["in_paper_scope"] is project["in_paper_scope"]
        assert item["fields"]["paper_cluster"] == project.get("paper_cluster")
        assert item["label"] == (project.get("name_en") or project.get("name_uk") or slug)
        assert item["created_by"] == "seed"
        assert item["derived"]["period"] == "unknown"
        assert item["virtual"] == {"open_comments": 0, "comment_count": 0, "open_proposals": 0}


def test_the_default_order_is_cluster_then_name(client: ApiClient) -> None:
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    order = {
        term["code"]: term["sort_order"]
        for term in next(v["terms"] for v in listing if v["name"] == "paper_cluster")
    }
    items = client.list("project")["items"]
    keys = [
        (order[item["fields"]["paper_cluster"]], sortkey(item["fields"]["name_en"] or ""))
        for item in items
        if item["fields"]["paper_cluster"]
    ]
    assert keys == sorted(keys)
    assert items[-1]["fields"]["paper_cluster"] is None  # NULLs last


def test_quick_filters_on_the_seed(client: ApiClient) -> None:
    def total(**params: Any) -> int:
        return int(client.list("project", **params)["total"])

    assert total(**{"f.in_paper_scope": "eq:true"}) == 19
    assert total(**{"f.in_paper_scope": "eq:false"}) == 1
    assert total(**{"f.verification_status": "in:unverified"}) == 20
    assert total(**{"f.open_comments": "range:1.."}) == 0
    assert total(**{"f.launch": "empty:true"}) == 20
    assert total(**{"f.period": "in:unknown"}) == 20


def test_text_filters_on_seeded_names(client: ApiClient) -> None:
    named = [project for project in seed_projects() if project.get("name_uk")]
    target = named[0]["name_uk"]
    expected = {p["slug"] for p in named if target.casefold() in p["name_uk"].casefold()}
    found = all_projects(client, **{"f.name_uk": f"contains:{target.upper()}"})
    assert {item["fields"]["slug"] for item in found} == expected
    found = all_projects(client, **{"f.name_uk": "empty:true"})
    assert len(found) == len(seed_projects()) - len(named)


# --------------------------------------------------------------------------------------
# Every vocabulary field
# --------------------------------------------------------------------------------------


def test_every_vocabulary_field_splits_the_seed_into_empty_and_set(client: ApiClient) -> None:
    fields = project_fields(client)
    vocab_fields = [name for name, field in fields.items() if field["vocabulary"]]
    assert {"paper_cluster", "status", "policy_domains", "period", "war_trajectory"} <= set(
        vocab_fields
    )
    for name in vocab_fields:
        empty = client.list("project", **{f"f.{name}": "empty:true"})["total"]
        filled = client.list("project", **{f"f.{name}": "empty:false"})["total"]
        assert empty + filled == 20, name


def test_filtering_by_every_vocabulary_field(client: ApiClient) -> None:
    fields = project_fields(client)
    for name, field in fields.items():
        if not field["vocabulary"] or field["derived"]:
            continue
        code = first_active_code(client, field["vocabulary"])
        value: Any = [code] if field["type"] == "vocab_list" else code
        project = client.create_project()
        note = "Synthetic verification note." if name == "verification_status" else None
        client.update("project", project, {name: value}, note=note)
        include, exclude = ("any", "none") if field["type"] == "vocab_list" else ("in", "nin")
        matched = all_projects(client, **{f"f.{name}": f"{include}:{code}"})
        assert project["id"] in {item["id"] for item in matched}, name
        assert all(
            (item["fields"][name] == value) or (code in (item["fields"][name] or []))
            for item in matched
        ), name
        others = all_projects(client, **{f"f.{name}": f"{exclude}:{code}"})
        assert project["id"] not in {item["id"] for item in others}, name
        if field["type"] == "vocab_list":
            both = all_projects(client, **{f"f.{name}": f"all:{code}"})
            assert project["id"] in {item["id"] for item in both}, name
        with_empty = all_projects(client, **{f"f.{name}": f"{include}:{code},~empty"})
        assert (
            len(with_empty)
            == len(matched) + client.list("project", **{f"f.{name}": "empty:true"})["total"]
        ), name


def test_filtering_by_the_derived_vocabulary_fields(client: ApiClient) -> None:
    invasion: date = load_parameters(REAL_CODEBOOK).full_scale_invasion
    project = client.create_project()
    event = {
        "subject_id": project["id"],
        "event_type": "launch",
        "date": f"{invasion.year + 1}-06",
        "date_basis": "stated_in_source",
    }
    client.create("event", event)
    item = client.item("project", project["id"])
    assert (item["derived"]["period"], item["derived"]["war_trajectory"]) == (
        "full_scale_war",
        "new_in_war",
    )
    for name, code in (("period", "full_scale_war"), ("war_trajectory", "new_in_war")):
        matched = all_projects(client, **{f"f.{name}": f"in:{code}"})
        assert [entry["id"] for entry in matched] == [project["id"]]
        unknown = all_projects(client, **{f"f.{name}": "in:unknown"})
        assert len(unknown) == 20 and project["id"] not in {e["id"] for e in unknown}
    launched = all_projects(client, **{"f.launch": f"within:{invasion.isoformat()}.."})
    assert [entry["id"] for entry in launched] == [project["id"]]


# --------------------------------------------------------------------------------------
# Sorting by every sortable field
# --------------------------------------------------------------------------------------


def _term_orders(client: ApiClient) -> dict[str, dict[str, int]]:
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    return {
        vocabulary["name"]: {
            term["code"]: (term["sort_order"] if term["sort_order"] is not None else 10**9)
            for term in vocabulary["terms"]
        }
        for vocabulary in listing
    }


def _sort_value(item: dict[str, Any], field: dict[str, Any], orders: dict[str, Any]) -> Any:
    """The primary sort key of API §4.2, computed in Python (None = empty)."""
    name, kind = field["name"], field["type"]
    if name in SYSTEM_KEYS or name == "version":
        value = item[name]
    elif field["derived"]:
        derived = item["derived"]
        if kind in ("partial_date", "date") and name != "existed_by":
            start, end = derived.get(f"{name}_start"), derived.get(f"{name}_end")
            return None if start is None else (start, end)
        value = derived[name]
    elif field["virtual"]:
        value = item["virtual"][name]
    else:
        value = item["fields"][name]
    if value is None or value == []:
        return None
    if kind == "vocab":
        return (orders[field["vocabulary"]].get(value, 10**9), value)
    if kind == "vocab_list":
        return (orders[field["vocabulary"]].get(value[0], 10**9), value[0])
    if kind in ("string", "text"):
        return sortkey(value)
    return value


def _add_varied_projects(client: ApiClient, fields: dict[str, dict[str, Any]]) -> None:
    """Three synthetic projects with different vocabulary values (and one left empty)."""
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    terms = {v["name"]: [t["code"] for t in v["terms"] if t["active"]] for v in listing}
    for index, name_en in enumerate(["Example B", "Example A", None]):
        changes: dict[str, Any] = {"name_uk": "Приклад" if name_en is None else None}
        for name, field in fields.items():
            if not field["vocabulary"] or field["derived"] or name == "verification_status":
                continue
            codes = terms[field["vocabulary"]]
            if index < 2 and len(codes) > index:
                code = codes[-1 - index]
                changes[name] = [code] if field["type"] == "vocab_list" else code
        project = client.create_project(name_en=name_en, name_uk=changes.pop("name_uk"))
        client.update("project", project, changes)


def test_sorting_by_every_sortable_field(client: ApiClient) -> None:
    fields = project_fields(client)
    _add_varied_projects(client, fields)
    orders = _term_orders(client)
    sortable = [field for field in fields.values() if field["sortable"]]
    assert len(sortable) >= 20
    expected_ids = {item["id"] for item in all_projects(client)}
    for field in sortable:
        for descending in (False, True):
            sort = ("-" if descending else "") + field["name"]
            items = all_projects(client, sort=sort)
            assert {item["id"] for item in items} == expected_ids, sort
            keys = [_sort_value(item, field, orders) for item in items]
            present = [key for key in keys if key is not None]
            assert keys[: len(present)] == present, f"{sort}: empty values must come last"
            assert present == sorted(present, reverse=descending), sort


def test_multi_field_sort_and_relevance(client: ApiClient) -> None:
    items = all_projects(client, sort="in_paper_scope,-name_en,slug")
    assert items[0]["fields"]["in_paper_scope"] is False
    response = client.get("/api/entities/project", {"sort": "relevance"})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_sort")
    name = seed_projects()[0]["name_en"]
    found = all_projects(client, q=name, sort="relevance")
    assert found and found[0]["label"] == name


@pytest.mark.parametrize("sort", ["name_en,name_uk,slug,status", "aliases", "-unknown"])
def test_invalid_sorts(client: ApiClient, sort: str) -> None:
    response = client.get("/api/entities/project", {"sort": sort})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_sort")


# --------------------------------------------------------------------------------------
# Facets
# --------------------------------------------------------------------------------------


def test_facets_of_a_vocabulary_field(client: ApiClient) -> None:
    facets = client.ok(client.get("/api/entities/project/facets", {"field": "paper_cluster"}))
    clusters = Counter(p["paper_cluster"] for p in seed_projects() if p.get("paper_cluster"))
    assert facets["field"] == "paper_cluster"
    assert {entry["value"]: entry["count"] for entry in facets["values"]} == {
        entry["value"]: clusters.get(entry["value"], 0) for entry in facets["values"]
    }
    assert set(clusters) <= {entry["value"] for entry in facets["values"]}
    assert facets["empty_count"] == 1
    orders = _term_orders(client)["paper_cluster"]
    assert [entry["value"] for entry in facets["values"]] == sorted(
        (entry["value"] for entry in facets["values"]), key=lambda code: orders[code]
    )
    assert all(isinstance(entry["label"], str) and entry["label"] for entry in facets["values"])


def test_facets_ignore_their_own_filter_but_apply_the_others(client: ApiClient) -> None:
    plain = client.ok(client.get("/api/entities/project/facets", {"field": "paper_cluster"}))
    code = plain["values"][0]["value"]
    own = client.get(
        "/api/entities/project/facets", {"field": "paper_cluster", "f.paper_cluster": f"in:{code}"}
    )
    assert client.ok(own) == plain
    other = client.ok(
        client.get(
            "/api/entities/project/facets",
            {"field": "paper_cluster", "f.in_paper_scope": "eq:false"},
        )
    )
    assert all(entry["count"] == 0 for entry in other["values"])
    assert other["empty_count"] == 1


def test_boolean_facets(client: ApiClient) -> None:
    facets = client.ok(client.get("/api/entities/project/facets", {"field": "in_paper_scope"}))
    assert facets["values"] == [
        {"value": "true", "label": "Yes", "count": 19},
        {"value": "false", "label": "No", "count": 1},
    ]


def test_facets_need_a_facet_field(client: ApiClient) -> None:
    for params in ({"field": "name_en"}, {"field": "nope"}, {}):
        response = client.get("/api/entities/project/facets", params)
        assert (response.status_code, error_of(response)["code"]) == (400, "bad_filter")
