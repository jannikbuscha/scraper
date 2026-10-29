"""Creating and editing entities over HTTP, and Definition of Done 4: a manual change
creates a revision with author and note; diff and restore work. Writes need no custom
request header."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import USER, ApiClient, error_of, project_data


def revisions(client: ApiClient, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    page = client.ok(client.get(f"/api/entities/{entity_type}/{entity_id}/revisions"))
    return list(page["items"])


# --------------------------------------------------------------------------------------
# Create and read
# --------------------------------------------------------------------------------------


def test_create_returns_the_item_and_its_revision(client: ApiClient) -> None:
    data = project_data(name_uk="Приклад", aliases=[{"text": "Example", "lang": "en"}])
    body = client.ok(client.post("/api/entities/project", {"data": data, "note": "Synthetic"}), 201)
    assert set(body) == {"item", "revision_id", "warnings"}
    item = body["item"]
    assert item["id"].startswith("prj_") and item["version"] == 1
    assert (item["created_by"], item["updated_by"]) == (USER, USER)
    assert item["fields"]["name_uk"] == "Приклад"
    assert item["fields"]["aliases"][0] == {
        "text": "Example",
        "lang": "en",
        "case_sensitive": True,
        "kind": "name",
        "exclude_patterns": [],
    }
    assert item["field_meta"]["slug"] == {
        "src": "manual",
        "by": USER,
        "at": item["created_at"],
        "locked": True,
        "verified": "unverified",
        "evidence_id": None,
        "restored_from_version": None,
    }
    assert "seed_key" not in item["fields"]
    assert body["warnings"] == []
    [revision] = revisions(client, "project", item["id"])
    assert (revision["id"], revision["action"], revision["note"]) == (
        body["revision_id"],
        "create",
        "Synthetic",
    )
    assert (revision["author"], revision["channel"]) == (USER, "ui")


def test_detail_items_have_field_comment_counts(client: ApiClient) -> None:
    project = client.create_project()
    client.comment(project["id"], field="name_en")
    client.comment(project["id"])
    item = client.item("project", project["id"])
    assert item["virtual"]["open_comments_by_field"] == {"name_en": 1, "": 1}
    assert item["virtual"]["open_comments"] == 2
    listed = client.list("project", **{"f.slug": f"eq:{project['fields']['slug']}"})["items"]
    assert "open_comments_by_field" not in listed[0]["virtual"]


def test_create_validation_errors(client: ApiClient) -> None:
    response = client.post("/api/entities/project", {"data": project_data(scope_note=None)})
    assert response.status_code == 400
    assert "scope_note" in error_of(response)["details"]
    response = client.post("/api/entities/project", {"data": project_data(nope=1)})
    assert error_of(response)["details"] == {"nope": ["is not a field of this entity type"]}
    response = client.post("/api/entities/project", {"data": project_data(seed_key="x")})
    assert error_of(response)["code"] == "validation_error"
    response = client.post(
        "/api/entities/document", {"data": {"title": "Example", "canonical_url": "https://x.org"}}
    )
    assert "canonical_url" in error_of(response)["details"]
    response = client.post("/api/entities/project", {"data": project_data(status="no_such")})
    assert "status" in error_of(response)["details"]


def test_duplicate_slugs_are_unique_violations(client: ApiClient) -> None:
    first = client.create_project()
    response = client.post(
        "/api/entities/project", {"data": project_data(slug=first["fields"]["slug"])}
    )
    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "unique_violation"
    assert error["details"] == {
        "field": "slug",
        "existing": {"id": first["id"], "label": first["label"], "deleted": False},
    }


def test_comments_are_not_served_by_the_generic_endpoints(client: ApiClient) -> None:
    project = client.create_project()
    comment = client.comment(project["id"])
    assert client.get(f"/api/entities/comment/{comment['id']}").status_code == 404
    response = client.post("/api/entities/comment", {"data": {"body_md": "x"}})
    assert response.status_code == 404
    response = client.patch(
        f"/api/entities/comment/{comment['id']}",
        {"changes": {"body_md": "Changed"}},
    )
    assert response.status_code == 404
    assert client.get(f"/api/entities/comment/{comment['id']}/revisions").status_code == 404


def test_an_id_of_another_type_is_not_found(client: ApiClient) -> None:
    project = client.create_project()
    assert client.get(f"/api/entities/service/{project['id']}").status_code == 404
    response = client.patch(f"/api/entities/service/{project['id']}", {"changes": {}})
    assert response.status_code == 404


# --------------------------------------------------------------------------------------
# DoD 4: revision with author and note
# --------------------------------------------------------------------------------------


def test_a_manual_change_creates_a_revision_with_author_and_note(client: ApiClient) -> None:
    seeded = client.list("project", sort="slug")["items"][0]
    body = client.update(
        "project", seeded, {"notes": "Example note from a test."}, note="Why: test"
    )
    assert body["changed"] is True and isinstance(body["revision_id"], int)
    item = body["item"]
    assert (item["version"], item["updated_by"]) == (2, USER)
    assert item["fields"]["notes"] == "Example note from a test."
    assert item["field_meta"]["notes"]["src"] == "manual"
    assert item["field_meta"]["notes"]["locked"] is True
    latest = revisions(client, "project", seeded["id"])[0]
    assert latest == {
        "id": body["revision_id"],
        "version": 2,
        "at": item["updated_at"],
        "author": USER,
        "channel": "ui",
        "action": "update",
        "note": "Why: test",
        "changed_fields": ["notes"],
        "restored_from": None,
        "restored_from_version": None,
        "batch_id": None,
    }
    full = client.ok(client.get(f"/api/entities/project/{seeded['id']}/revisions/2"))
    diff = full["revision"]["diff"]
    assert diff["fields"] == {"notes": [None, "Example note from a test."]}
    assert diff["meta"]["notes"]["src"] == [None, "manual"]
    assert full["revision"]["snapshot"]["fields"]["notes"] == "Example note from a test."
    assert full["revision"]["schema_revision"]


def test_a_no_op_patch_writes_nothing(client: ApiClient) -> None:
    project = client.create_project()
    body = client.update("project", project, {"name_en": "  Example project  "})
    assert (body["changed"], body["revision_id"], body["item"]["version"]) == (False, None, 1)
    assert len(revisions(client, "project", project["id"])) == 1


def test_patch_validation(client: ApiClient) -> None:
    project = client.create_project()
    url = f"/api/entities/project/{project['id']}"
    response = client.patch(url, {"changes": {"slug": "Not A Slug"}})
    assert "slug" in error_of(response)["details"]
    response = client.patch(url, {"changes": {"period": "unknown"}})
    assert error_of(response)["details"] == {"period": ["is derived and cannot be set"]}
    response = client.patch(url, {"changes": {"in_paper_scope": True}})
    assert "scope_note" in error_of(response)["details"]
    response = client.patch(url, {"changes": {"verification_status": "verified"}})
    assert "note" in error_of(response)["details"]
    response = client.patch(url, {"changes": {}, "note": "x" * 2001})
    assert "note" in error_of(response)["details"]


# --------------------------------------------------------------------------------------
# DoD 4: diff and restore
# --------------------------------------------------------------------------------------


def _three_versions(client: ApiClient) -> dict[str, Any]:
    project = client.create_project(name_en="Example one")
    project = client.update("project", project, {"name_en": "Example two"})["item"]
    return dict(client.update("project", project, {"notes": "Example note"})["item"])


def test_diff_between_two_versions(client: ApiClient) -> None:
    project = _three_versions(client)
    url = f"/api/entities/project/{project['id']}/diff"
    body = client.ok(client.get(url, {"from": 1, "to": 3}))
    assert (body["from"], body["to"], body["not_recorded"]) == (1, 3, [])
    assert body["diff"]["fields"] == {
        "name_en": ["Example one", "Example two"],
        "notes": [None, "Example note"],
    }
    assert "name_en" not in body["diff"]["meta"]  # same source and author, only a new time
    assert body["diff"]["meta"]["notes"]["src"] == [None, "manual"]
    created = client.ok(client.get(url, {"from": 0, "to": 1}))["diff"]["fields"]
    assert created["name_en"] == [None, "Example one"]
    response = client.get(url, {"from": 3, "to": 1})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
    response = client.get(url, {"from": 1, "to": 9})
    assert (response.status_code, error_of(response)["code"]) == (404, "not_found")


def test_restore_previews_and_creates_a_new_revision(client: ApiClient) -> None:
    project = _three_versions(client)
    url = f"/api/entities/project/{project['id']}/restore"
    preview = client.ok(client.post(url, {"version": 1, "dry_run": True, "note": "x"}))
    assert preview["changes"] == {
        "name_en": ["Example two", "Example one"],
        "notes": ["Example note", None],
    }
    assert (preview["changed"], preview["revision_id"], preview["item"]["version"]) == (
        False,
        None,
        3,
    )
    body = client.ok(
        client.post(url, {"version": 1, "fields": ["name_en"], "note": "Undo the name"})
    )
    assert body["changed"] is True and body["changes"] == {
        "name_en": ["Example two", "Example one"]
    }
    item = body["item"]
    assert (item["version"], item["fields"]["name_en"], item["fields"]["notes"]) == (
        4,
        "Example one",
        "Example note",
    )
    assert item["field_meta"]["name_en"]["restored_from_version"] == 1
    assert item["field_meta"]["name_en"]["by"] == USER
    latest = revisions(client, "project", project["id"])[0]
    assert (latest["action"], latest["channel"], latest["author"]) == ("restore", "restore", USER)
    assert (latest["restored_from_version"], latest["note"]) == (1, "Undo the name")
    assert [entry["version"] for entry in revisions(client, "project", project["id"])] == [
        4,
        3,
        2,
        1,
    ]


def test_restore_errors(client: ApiClient) -> None:
    project = _three_versions(client)
    url = f"/api/entities/project/{project['id']}/restore"
    response = client.post(url, {"version": 99})
    assert (response.status_code, error_of(response)["code"]) == (404, "not_found")
    response = client.post(url, {"version": 1, "fields": ["nope"]})
    assert "fields" in error_of(response)["details"]


# --------------------------------------------------------------------------------------
# Writes without custom headers; deleted records
# --------------------------------------------------------------------------------------


def test_writes_need_no_custom_headers(client: ApiClient) -> None:
    project = client.create_project(name_en="Example base")
    url = f"/api/entities/project/{project['id']}"
    first = client.client.patch(url, json={"changes": {"name_en": "Example first"}})
    second = client.client.patch(url, json={"changes": {"name_en": "Example second"}})
    assert (first.status_code, second.status_code) == (200, 200)
    assert second.json()["item"]["version"] == 3
    latest = revisions(client, "project", project["id"])[0]
    assert (latest["version"], latest["author"], latest["channel"]) == (3, USER, "ui")


def test_writes_to_a_deleted_record_are_refused(client: ApiClient) -> None:
    project = client.create_project()
    client.ok(client.post(f"/api/entities/project/{project['id']}/delete", {}))
    response = client.patch(f"/api/entities/project/{project['id']}", {"changes": {"notes": "x"}})
    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "entity_deleted"
    assert error["details"]["deleted_by"] == USER and error["details"]["deleted_at"]
    response = client.post(f"/api/entities/project/{project['id']}/restore", {"version": 1})
    assert error_of(response)["code"] == "entity_deleted"
