"""Recent changes and revisions by ID (API §3.2, §3.4)."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import USER, ApiClient, error_of

ITEM_KEYS = {
    "id", "entity_type", "entity_id", "entity_label", "version", "at", "author", "channel",
    "action", "note", "changed_fields", "restored_from_version", "batch_id", "run_id",
    "proposal_id", "context",
}  # fmt: skip


def feed(client: ApiClient, **params: Any) -> dict[str, Any]:
    return client.ok(client.get("/api/revisions", params))


def test_recent_changes_newest_first(client: ApiClient) -> None:
    seeded_total = feed(client)["total"]
    assert seeded_total > 20  # vocabulary terms, the organisation and the projects
    project = client.create_project()
    client.update("project", project, {"notes": "Example"}, note="Second")
    page = feed(client, page_size=2)
    assert page["total"] == seeded_total + 2
    assert (page["page"], page["page_size"]) == (1, 2)
    newest, older = page["items"]
    assert set(newest) == ITEM_KEYS
    assert (newest["entity_id"], newest["version"], newest["author"]) == (project["id"], 2, USER)
    assert (newest["note"], newest["changed_fields"]) == ("Second", ["notes"])
    assert newest["entity_label"] == project["label"] and newest["context"] is None
    assert (older["action"], older["author"]) == ("create", USER)
    assert newest["id"] > older["id"]


def test_recent_changes_filters(client: ApiClient) -> None:
    project = client.create_project()
    client.update("project", project, {"notes": "Example"})
    client.comment(project["id"])
    ui = feed(client, channel="ui")
    assert ui["total"] == 3
    assert {entry["author"] for entry in ui["items"]} == {USER}
    assert feed(client, entity_type="comment")["total"] == 1
    assert feed(client, entity_type="project,comment", channel="ui")["total"] == 3
    assert feed(client, channel="seed", entity_type="project")["total"] == 20
    assert feed(client, action="update", channel="ui")["total"] == 1
    assert feed(client, entity_id=project["id"])["total"] == 2
    created_at = project["created_at"]
    assert feed(client, since=created_at, channel="ui")["total"] == 3
    assert feed(client, until="2000-01-01")["total"] == 0
    day = created_at[:10]
    assert feed(client, since=day, until=day, channel="ui")["total"] == 3
    for params in ({"channel": "web"}, {"action": "edit"}, {"since": "yesterday"}):
        response = client.get("/api/revisions", params)
        assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")


def test_the_author_filter_and_the_authors_list_are_gone(client: ApiClient) -> None:
    project = client.create_project()
    # An unknown parameter is ignored like any other.
    assert feed(client, author="seed")["total"] == feed(client)["total"]
    response = client.get("/api/revisions/authors")
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
    assert client.ok(client.get("/api/comments", {"author": "seed"}))["total"] == 0
    client.comment(project["id"])
    assert client.ok(client.get("/api/comments", {"author": "seed"}))["total"] == 1


def test_revision_by_id(client: ApiClient) -> None:
    project = client.create_project()
    service = client.create("service", {"project_id": project["id"], "name_en": "Example svc"})
    revision_id = feed(client, entity_id=service["id"])["items"][0]["id"]
    body = client.ok(client.get(f"/api/revisions/{revision_id}"))
    assert set(body) == {"revision", "entity_type", "entity_id", "entity_label", "refs"}
    assert (body["entity_type"], body["entity_id"], body["entity_label"]) == (
        "service",
        service["id"],
        service["label"],
    )
    assert body["revision"]["snapshot"]["fields"]["project_id"] == project["id"]
    assert body["refs"][project["id"]]["label"] == project["label"]
    comment = client.comment(project["id"])
    comment_revision = feed(client, entity_id=comment["id"])["items"][0]["id"]
    body = client.ok(client.get(f"/api/revisions/{comment_revision}"))
    assert body["entity_type"] == "comment"
    assert body["entity_label"].startswith("Comment on")
    response = client.get("/api/revisions/987654321")
    assert (response.status_code, error_of(response)["code"]) == (404, "not_found")


def test_entity_revision_paging(client: ApiClient) -> None:
    project = client.create_project()
    for index in range(3):
        project = client.update("project", project, {"notes": f"Example {index}"})["item"]
    url = f"/api/entities/project/{project['id']}/revisions"
    page = client.ok(client.get(url, {"page_size": 2, "page": 2}))
    assert (page["total"], [entry["version"] for entry in page["items"]]) == (4, [2, 1])
    assert set(page) == {"items", "total", "page", "page_size", "refs"}
    response = client.get(url, {"page": "0"})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
