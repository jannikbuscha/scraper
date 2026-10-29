"""Definition of Done 6 over HTTP: comment threads (open/resolved) on every kind of
entity, filterable; plus editing, deleting, restoring and the rendered Markdown."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import ALICE, BOB, ApiClient, error_of

COMMENT_KEYS = {
    "id", "subject_id", "subject_type", "subject_label", "field", "parent_id", "body_md",
    "body_html", "status", "resolved_by", "resolved_at", "created_at", "created_by",
    "updated_at", "updated_by", "version", "edited", "deleted_at", "deleted_by",
}  # fmt: skip


def subjects(client: ApiClient) -> dict[str, dict[str, Any]]:
    """One synthetic record of several entity types, plus a seeded project and a term."""
    project = client.create_project()
    service = client.create("service", {"project_id": project["id"], "name_en": "Example svc"})
    event = client.create("event", {"subject_id": project["id"], "event_type": "announced"})
    document = client.create("document", {"title": "Example document"})
    organization = client.create("organization", {"name_en": "Example org"})
    view = client.create(
        "saved_view", {"name": "Example view", "entity_type": "event", "query": "sort=-date"}
    )
    seeded = client.list("project", sort="slug")["items"][0]
    term = client.list("vocabulary_term", **{"f.vocabulary": "eq:status"})["items"][0]
    return {
        "project": project,
        "service": service,
        "event": event,
        "document": document,
        "organization": organization,
        "saved_view": view,
        "seeded project": seeded,
        "vocabulary_term": term,
    }


def threads(client: ApiClient, subject_id: str, **params: Any) -> list[dict[str, Any]]:
    body = client.ok(client.get("/api/comments", {"subject_id": subject_id, **params}))
    return list(body["threads"])


def test_threads_on_every_kind_of_entity(client: ApiClient) -> None:
    for kind, subject in subjects(client).items():
        root = client.comment(subject["id"], f"Example root on the {kind}.")
        assert set(root) == COMMENT_KEYS
        assert (root["status"], root["parent_id"], root["subject_label"]) == (
            "open",
            None,
            subject["label"],
        )
        assert root["subject_type"] == subject["type"]
        reply = client.comment(subject["id"], "Example reply.", parent_id=root["id"], author=BOB)
        assert (reply["status"], reply["parent_id"]) == (None, root["id"])
        [thread] = threads(client, subject["id"])
        assert thread["root"]["id"] == root["id"]
        assert [entry["id"] for entry in thread["replies"]] == [reply["id"]]
        item = client.item(subject["type"], subject["id"])
        assert item["virtual"]["open_comments"] == 1 and item["virtual"]["comment_count"] == 2, kind


def test_thread_order_and_field_threads(client: ApiClient) -> None:
    project = client.create_project()
    first = client.comment(project["id"], "First root.")
    second = client.comment(project["id"], "Second root.", field="name_en")
    replies = [
        client.comment(project["id"], f"Reply {index}.", parent_id=first["id"])
        for index in range(2)
    ]
    assert second["field"] == "name_en"
    listed = threads(client, project["id"])
    assert [thread["root"]["id"] for thread in listed] == [second["id"], first["id"]]
    assert [reply["id"] for reply in listed[1]["replies"]] == [reply["id"] for reply in replies]
    assert [t["root"]["id"] for t in threads(client, project["id"], field="-")] == [first["id"]]
    assert [t["root"]["id"] for t in threads(client, project["id"], field="name_en")] == [
        second["id"]
    ]
    field_reply = client.comment(project["id"], "On the field.", parent_id=second["id"])
    assert field_reply["field"] == "name_en"


def test_resolve_and_reopen(client: ApiClient) -> None:
    project = client.create_project()
    root = client.comment(project["id"])
    url = f"/api/comments/{root['id']}"
    body = client.ok(client.post(f"{url}/resolve", {"expected_version": 1}, author=BOB))
    assert body["changed"] is True
    comment = body["comment"]
    assert (comment["status"], comment["resolved_by"], comment["version"]) == ("resolved", BOB, 2)
    assert comment["resolved_at"]
    # Idempotent: no revision and no version check when the status is already set.
    again = client.ok(client.post(f"{url}/resolve", {"expected_version": 1}))
    assert (again["changed"], again["comment"]["version"]) == (False, 2)
    reopened = client.ok(client.post(f"{url}/reopen", {"expected_version": 2}))
    assert (reopened["changed"], reopened["comment"]["status"]) == (True, "open")
    assert reopened["comment"]["resolved_by"] is None
    response = client.post(f"{url}/resolve", {"expected_version": 1})
    assert (response.status_code, error_of(response)["details"]["action"]) == (409, "comment")
    reply = client.comment(project["id"], parent_id=root["id"])
    response = client.post(f"/api/comments/{reply['id']}/resolve", {"expected_version": 1})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
    response = client.post(f"{url}/resolve", {"expected_version": 3, "note": "x"})
    assert error_of(response)["details"] == {"note": ["Extra inputs are not permitted"]}


def test_the_open_comments_quick_filter(client: ApiClient) -> None:
    quiet = client.create_project()
    commented = client.create_project()
    root = client.comment(commented["id"], field="slug")
    query = {"f.open_comments": "range:1.."}
    assert [item["id"] for item in client.list("project", **query)["items"]] == [commented["id"]]
    client.ok(client.post(f"/api/comments/{root['id']}/resolve", {"expected_version": 1}))
    assert client.list("project", **query)["items"] == []
    assert quiet["id"] not in {item["id"] for item in client.list("project", **query)["items"]}
    counted = client.list("project", **{"f.comment_count": "range:1.."})["items"]
    assert [item["id"] for item in counted] == [commented["id"]]


def test_the_comment_feed_and_its_filters(client: ApiClient) -> None:
    things = subjects(client)
    project_root = client.comment(things["project"]["id"], "About the zephyr pipeline.")
    service_root = client.comment(things["service"]["id"], "Service remark.", author=BOB)
    client.comment(things["project"]["id"], "Reply.", parent_id=project_root["id"], author=BOB)
    client.ok(client.post(f"/api/comments/{service_root['id']}/resolve", {"expected_version": 1}))

    def feed(**params: Any) -> list[str]:
        body = client.ok(client.get("/api/comments", params))
        return [item["root"]["id"] for item in body["items"]]

    page = client.ok(client.get("/api/comments"))
    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["total"] == 2
    # Newest activity first: resolving the service thread was the last change.
    assert feed() == [service_root["id"], project_root["id"]]
    second = page["items"][1]
    assert (second["reply_count"], bool(second["last_activity_at"])) == (1, True)
    assert feed(status="open") == [project_root["id"]]
    assert feed(status="resolved") == [service_root["id"]]
    assert feed(entity_type="service") == [service_root["id"]]
    assert set(feed(entity_type="project,service")) == {project_root["id"], service_root["id"]}
    assert set(feed(author=BOB)) == {project_root["id"], service_root["id"]}
    assert feed(author=ALICE) == [project_root["id"]]
    assert feed(q="zephyr") == [project_root["id"]]
    assert client.ok(client.get("/api/comments", {"page_size": 1, "page": 2}))["page"] == 2
    response = client.get("/api/comments", {"status": "closed"})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")


def test_editing_a_comment(client: ApiClient) -> None:
    project = client.create_project()
    root = client.comment(project["id"], "Example **draft**.")
    url = f"/api/comments/{root['id']}"
    body = client.ok(
        client.patch(url, {"expected_version": 1, "body_md": "Example final.", "note": "Typo"})
    )
    assert (body["comment"]["body_md"], body["comment"]["edited"]) == ("Example final.", True)
    response = client.patch(url, {"expected_version": 1, "body_md": "Other."}, author=BOB)
    assert response.status_code == 409
    payload = error_of(response)["details"]
    assert (payload["action"], payload["entity_type"]) == ("comment", "comment")
    response = client.patch(url, {"expected_version": 2, "body_md": "x" * 10_001})
    assert "body_md" in error_of(response)["details"]


def test_comment_validation(client: ApiClient) -> None:
    project = client.create_project()
    root = client.comment(project["id"])
    cases: list[tuple[dict[str, Any], str]] = [
        ({"subject_id": project["id"]}, "body_md"),
        ({"subject_id": project["id"], "body_md": "x", "field": "nope"}, "field"),
        ({"subject_id": root["id"], "body_md": "x"}, "subject_id"),
        ({"subject_id": "prj_01JBX3AAAAAAAAAAAAAAAAAAAA", "body_md": "x"}, "subject_id"),
        ({"subject_id": project["id"], "body_md": "   "}, "body_md"),
    ]
    for body, path in cases:
        response = client.post("/api/comments", body)
        assert response.status_code == 400, body
        assert path in error_of(response)["details"], (body, error_of(response))


def test_deleting_a_root_hides_its_thread(client: ApiClient) -> None:
    project = client.create_project()
    root = client.comment(project["id"])
    reply = client.comment(project["id"], parent_id=root["id"])
    url = f"/api/comments/{root['id']}"
    deleted = client.ok(client.post(f"{url}/delete", {"expected_version": 1, "note": "Off-topic"}))
    assert deleted["comment"]["deleted_by"] == ALICE
    assert threads(client, project["id"]) == []
    [hidden] = threads(client, project["id"], deleted="only")
    assert [entry["id"] for entry in hidden["replies"]] == [reply["id"]]
    assert client.item("project", project["id"])["virtual"]["open_comments"] == 0
    reply = {"subject_id": project["id"], "body_md": "x", "parent_id": root["id"]}
    response = client.post("/api/comments", reply)
    assert "parent_id" in error_of(response)["details"]
    client.ok(client.post(f"{url}/undelete", {"expected_version": 2}))
    assert [t["root"]["id"] for t in threads(client, project["id"])] == [root["id"]]


def test_comment_history_and_restore(client: ApiClient) -> None:
    project = client.create_project()
    root = client.comment(project["id"], "Version one.")
    url = f"/api/comments/{root['id']}"
    client.ok(client.patch(url, {"expected_version": 1, "body_md": "Version two."}))
    history = client.ok(client.get(f"{url}/revisions"))
    assert [entry["version"] for entry in history["items"]] == [2, 1]
    first = client.ok(client.get(f"{url}/revisions/1"))["revision"]
    assert first["snapshot"]["fields"]["body_md"] == "Version one."
    diff = client.ok(client.get(f"{url}/diff", {"from": 1, "to": 2}))["diff"]
    assert diff["fields"]["body_md"] == ["Version one.", "Version two."]
    restored = client.ok(
        client.post(f"{url}/restore", {"expected_version": 2, "version": 1, "note": "Back"})
    )
    assert restored["comment"]["body_md"] == "Version one."
    latest = client.ok(client.get(f"{url}/revisions"))["items"][0]
    assert (latest["action"], latest["channel"]) == ("restore", "restore")
    changes = client.ok(client.get("/api/revisions", {"entity_type": "comment"}))["items"]
    assert changes[0]["context"] == {
        "subject_id": project["id"],
        "subject_type": "project",
        "field": None,
        "parent_id": None,
    }


def test_markdown_is_rendered_and_sanitised(client: ApiClient) -> None:
    project = client.create_project()
    body = (
        "**Bold** <script>alert(1)</script> [link](javascript:alert(1)) "
        '[ok](https://example.org "Title") <img src=x onerror=alert(1)> //example.org'
    )
    html = client.comment(project["id"], body)["body_html"]
    assert "<strong>Bold</strong>" in html
    # Raw HTML is escaped text, unsafe links stay text, protocol-relative hrefs are dropped.
    assert "<script" not in html
    assert "&lt;script&gt;" in html
    assert "<img" not in html
    assert 'href="javascript:' not in html
    assert 'href="//' not in html
    assert '<a href="https://example.org" rel="noopener noreferrer nofollow">ok</a>' in html
    assert "title=" not in html
