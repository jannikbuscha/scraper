"""Saved views, vocabulary terms and the other entity types through the generic
endpoints (API §2, §3.2)."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import ApiClient, error_of


def test_saved_views_round_trip(client: ApiClient) -> None:
    view = client.create(
        "saved_view",
        {
            "name": "Example view",
            "entity_type": "project",
            "query": "f.in_paper_scope=eq%3Atrue&sort=name_en",
            "description": "Synthetic.",
        },
    )
    assert view["label"] == "Example view"
    listed = client.list("saved_view", **{"f.entity_type": "eq:project"})["items"]
    assert [item["id"] for item in listed] == [view["id"]]
    assert client.list("saved_view", **{"f.entity_type": "eq:event"})["items"] == []
    renamed = client.update("saved_view", view, {"name": "Example view (renamed)"})["item"]
    assert renamed["version"] == 2
    url = f"/api/entities/saved_view/{view['id']}"
    client.ok(client.post(f"{url}/delete", {}))
    assert client.list("saved_view")["items"] == []
    trash = client.list("saved_view", deleted="only")["items"]
    assert [item["fields"]["name"] for item in trash] == ["Example view (renamed)"]
    client.ok(client.post(f"{url}/undelete", {}))
    assert len(client.list("saved_view")["items"]) == 1


def test_saved_views_validate_the_table_type(client: ApiClient) -> None:
    response = client.post(
        "/api/entities/saved_view",
        {"data": {"name": "Example", "entity_type": "comment", "query": "sort=name_en"}},
    )
    assert "entity_type" in error_of(response)["details"]


def _term(client: ApiClient, vocabulary: str, code: str) -> dict[str, Any]:
    items = client.list(
        "vocabulary_term", **{"f.vocabulary": f"eq:{vocabulary}", "f.code": f"eq:{code}"}
    )["items"]
    assert len(items) == 1
    return dict(items[0])


def test_vocabulary_terms_through_the_generic_endpoints(client: ApiClient) -> None:
    term = client.create(
        "vocabulary_term",
        {"vocabulary": "status", "code": "example_status", "label_en": "Example status"},
    )
    assert term["label"] == "status:example_status"
    updated = client.update(
        "vocabulary_term", term, {"label_en": "Example status (edited)"}, note="Synthetic"
    )["item"]
    assert updated["fields"]["label_en"] == "Example status (edited)"
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    status_terms = next(v["terms"] for v in listing if v["name"] == "status")
    assert {"code": "example_status", "label_en": "Example status (edited)"}.items() <= next(
        t for t in status_terms if t["code"] == "example_status"
    ).items()
    project = client.create_project(status="example_status")
    assert project["fields"]["status"] == "example_status"
    changes = client.ok(client.get("/api/revisions", {"entity_type": "vocabulary_term"}))
    assert changes["items"][0]["context"] == {"vocabulary": "status"}


def test_vocabulary_term_rules(client: ApiClient) -> None:
    response = client.post(
        "/api/entities/vocabulary_term",
        {"data": {"vocabulary": "verification_status", "code": "example", "label_en": "X"}},
    )
    assert (response.status_code, error_of(response)["code"]) == (409, "fixed_code")
    launch = _term(client, "event_type", "launch")
    response = client.patch(
        f"/api/entities/vocabulary_term/{launch['id']}",
        {"changes": {"active": False}},
    )
    assert (response.status_code, error_of(response)["code"]) == (409, "fixed_code")
    response = client.patch(
        f"/api/entities/vocabulary_term/{launch['id']}",
        {"changes": {"code": "renamed"}},
    )
    assert error_of(response)["details"] == {"code": ["can only be set when the record is created"]}
    response = client.post(
        "/api/entities/vocabulary_term",
        {"data": {"vocabulary": "status", "code": "active", "label_en": "Duplicate"}},
    )
    assert (response.status_code, error_of(response)["code"]) == (409, "unique_violation")


def test_events_documents_and_organizations(client: ApiClient) -> None:
    project = client.create_project()
    event = client.create(
        "event",
        {
            "subject_id": project["id"],
            "event_type": "announced",
            "date": "2024-Q2",
            "date_basis": "stated_in_source",
            "description_en": "Example event.",
        },
    )
    assert event["refs"]["subject_id"] == {
        "id": project["id"],
        "type": "project",
        "label": project["label"],
        "deleted": False,
    }
    assert event["fields"]["date"] == "2024-Q2"
    response = client.post(
        "/api/entities/event",
        {"data": {"subject_id": project["id"], "event_type": "announced", "date": "2024"}},
    )
    assert "date_basis" in error_of(response)["details"]
    document = client.create(
        "document",
        {
            "title": "Example document",
            "url": "https://Example.org/page/?utm_source=x#top",
            "retrieved_at": "2026-10-01T10:00:00Z",
            "links": [{"subject_id": project["id"], "state": "confirmed"}],
        },
    )
    assert document["fields"]["canonical_url"] == "https://example.org/page"
    assert document["fields"]["links"][0]["origin"] == "manual"
    assert document["fields"]["text"] is None  # detail responses carry the text
    assert f"links.{project['id']}" in document["refs"]
    linked = client.list("document", **{"f.links": f"confirmed:{project['id']}"})["items"]
    assert [item["id"] for item in linked] == [document["id"]]
    assert "text" not in linked[0]["fields"]
    in_scope = client.list("document", **{"f.linked_in_paper_scope": "eq:true"})["total"]
    assert in_scope == 0  # the synthetic project is not in scope
    organization = client.create("organization", {"name_en": "Example agency", "country": "ua"})
    assert organization["fields"]["country"] == "UA"


def test_participations_and_relations(client: ApiClient) -> None:
    project = client.create_project()
    other = client.create_project()
    organization = client.create("organization", {"name_en": "Example partner"})
    participation = client.create(
        "participation",
        {"organization_id": organization["id"], "subject_id": project["id"], "role": "partner"},
    )
    assert participation["label"].startswith("Example partner")
    relation = client.create(
        "relation",
        {"from_id": project["id"], "to_id": other["id"], "relation_type": "related_to"},
    )
    found = client.list("relation", **{"f.endpoint": f"in:{other['id']}"})["items"]
    assert [item["id"] for item in found] == [relation["id"]]
    indicator = client.create(
        "indicator", {"subject_id": project["id"], "metric": "Example metric", "value": 3}
    )
    assert indicator["fields"]["value"] == 3


def test_search_finds_entities(client: ApiClient) -> None:
    project = client.create_project(name_en="Example Zephyrine project")
    found = client.list("project", q="zephyr")["items"]
    assert [item["id"] for item in found] == [project["id"]]
    assert client.list("project", q="-")["total"] == 0
    assert client.list("project", q=" ".join(["zephyr"] * 17))["total"] == 1
