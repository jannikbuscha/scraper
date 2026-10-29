"""Soft delete, undelete (with cascade), field verification and bulk edit over HTTP."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import USER, ApiClient, error_of


def _project_with_services(client: ApiClient, count: int = 2) -> tuple[dict[str, Any], list[str]]:
    project = client.create_project()
    services = [
        client.create("service", {"project_id": project["id"], "name_en": f"Example service {i}"})
        for i in range(count)
    ]
    return project, [service["id"] for service in services]


# --------------------------------------------------------------------------------------
# Delete and undelete
# --------------------------------------------------------------------------------------


def test_delete_with_dependents_needs_cascade(client: ApiClient) -> None:
    project, service_ids = _project_with_services(client)
    url = f"/api/entities/project/{project['id']}"
    response = client.post(f"{url}/delete", {"note": "Example"})
    assert response.status_code == 409
    assert error_of(response) | {"message": ""} == {
        "code": "has_dependents",
        "message": "",
        "details": {"service": 2},
    }
    body = client.ok(client.post(f"{url}/delete", {"cascade": True}))
    assert set(body) == {"item", "revision_id", "batch_id"}
    assert body["item"]["deleted_at"] and body["item"]["deleted_by"] == USER
    for service_id in service_ids:
        assert client.item("service", service_id)["deleted_at"] is not None
    batch = client.ok(client.get("/api/revisions", {"batch_id": body["batch_id"]}))
    assert {entry["entity_id"] for entry in batch["items"]} == {project["id"], *service_ids}
    assert project["id"] not in {item["id"] for item in client.list("project")["items"]}
    trash = client.list("project", deleted="only")["items"]
    assert [item["id"] for item in trash] == [project["id"]]


def test_undelete_with_cascade_brings_back_the_batch(client: ApiClient) -> None:
    project, service_ids = _project_with_services(client)
    url = f"/api/entities/project/{project['id']}"
    client.ok(client.post(f"{url}/delete", {"cascade": True}))
    body = client.ok(client.post(f"{url}/undelete", {"cascade": True, "note": "Back"}))
    assert body["item"]["deleted_at"] is None and body["item"]["version"] == 3
    for service_id in service_ids:
        assert client.item("service", service_id)["deleted_at"] is None


def test_undelete_without_cascade_leaves_the_services_deleted(client: ApiClient) -> None:
    project, service_ids = _project_with_services(client, count=1)
    url = f"/api/entities/project/{project['id']}"
    client.ok(client.post(f"{url}/delete", {"cascade": True}))
    client.ok(client.post(f"{url}/undelete", {}))
    assert client.item("service", service_ids[0])["deleted_at"] is not None


def test_state_errors(client: ApiClient) -> None:
    project = client.create_project()
    url = f"/api/entities/project/{project['id']}"
    response = client.post(f"{url}/undelete", {})
    assert error_of(response) | {"message": ""} == {
        "code": "invalid_state",
        "message": "",
        "details": {"state": "live"},
    }
    client.ok(client.post(f"{url}/delete", {}))
    response = client.post(f"{url}/delete", {})
    assert error_of(response)["details"] == {"state": "deleted"}
    response = client.post(f"{url}/delete", {"cascade": "yes"})
    assert error_of(response)["details"] == {"cascade": ["Input should be a valid boolean"]}


def test_references_to_deleted_records(client: ApiClient) -> None:
    project = client.create_project()
    service = client.create("service", {"project_id": project["id"], "name_en": "Example"})
    client.ok(
        client.post(
            f"/api/entities/project/{project['id']}/delete",
            {"cascade": True},
        )
    )
    response = client.post(
        "/api/entities/service", {"data": {"project_id": project["id"], "name_en": "Example"}}
    )
    assert response.status_code == 409
    assert error_of(response)["details"] == {
        "field": "project_id",
        "id": project["id"],
        "type": "project",
        "label": project["label"],
    }
    # Undeleting the service alone is refused while its project is deleted.
    response = client.post(f"/api/entities/service/{service['id']}/undelete", {})
    assert error_of(response)["code"] == "reference_deleted"


def test_vocabulary_terms_cannot_be_deleted(client: ApiClient) -> None:
    term = client.list("vocabulary_term", **{"f.vocabulary": "eq:status"})["items"][0]
    response = client.post(f"/api/entities/vocabulary_term/{term['id']}/delete", {})
    assert (response.status_code, error_of(response)["code"]) == (409, "not_deletable")


# --------------------------------------------------------------------------------------
# Field verification
# --------------------------------------------------------------------------------------


def _evidence(client: ApiClient, subject_id: str, field: str) -> dict[str, Any]:
    return client.create(
        "evidence",
        {
            "subject_id": subject_id,
            "target": f"field:{field}",
            "url": "https://example.org/source",
            "quote": "Example quote.",
        },
    )


def test_verify_a_field_with_evidence(client: ApiClient) -> None:
    project = client.create_project()
    evidence = _evidence(client, project["id"], "name_en")
    assert evidence["fields"]["retrieved_at"]  # defaults to now on channel ui
    url = f"/api/entities/project/{project['id']}/verify-field"
    body = client.ok(
        client.post(
            url,
            {
                "field": "name_en",
                "status": "verified",
                "evidence_id": evidence["id"],
                "note": "Checked",
            },
        )
    )
    assert set(body) == {"item", "revision_id"}
    meta = body["item"]["field_meta"]["name_en"]
    assert (meta["verified"], meta["evidence_id"], meta["locked"]) == (
        "verified",
        evidence["id"],
        True,
    )
    assert body["item"]["version"] == 2
    latest = client.ok(client.get(f"/api/entities/project/{project['id']}/revisions"))["items"][0]
    assert (latest["action"], latest["author"], latest["changed_fields"]) == (
        "verify",
        USER,
        ["name_en"],
    )
    again = client.ok(
        client.post(
            url,
            {
                "field": "name_en",
                "status": "verified",
                "evidence_id": evidence["id"],
            },
        )
    )
    assert (again["revision_id"], again["item"]["version"]) == (None, 2)


def test_verification_rules(client: ApiClient) -> None:
    project = client.create_project()
    other = _evidence(client, project["id"], "slug")
    url = f"/api/entities/project/{project['id']}/verify-field"
    base = {"field": "name_en"}
    response = client.post(url, base | {"status": "verified"})
    assert (response.status_code, error_of(response)["code"]) == (400, "evidence_required")
    response = client.post(url, base | {"status": "verified", "evidence_id": other["id"]})
    assert error_of(response)["code"] == "evidence_required"
    response = client.post(url, base | {"status": "disputed"})
    assert "note" in error_of(response)["details"]
    response = client.post(url, base | {"status": "maybe"})
    assert "status" in error_of(response)["details"]
    response = client.post(url, base | {"field": "notes", "status": "disputed", "note": "x"})
    assert error_of(response)["details"] == {"field": ["An empty field cannot be verified"]}
    body = client.ok(client.post(url, base | {"status": "disputed", "note": "Sources differ"}))
    assert body["item"]["field_meta"]["name_en"]["verified"] == "disputed"


def test_evidence_of_a_verified_field_cannot_be_deleted(client: ApiClient) -> None:
    project = client.create_project()
    evidence = _evidence(client, project["id"], "name_en")
    verify = f"/api/entities/project/{project['id']}/verify-field"
    base = {"field": "name_en", "evidence_id": evidence["id"]}
    client.ok(client.post(verify, base | {"status": "verified"}))
    delete = f"/api/entities/evidence/{evidence['id']}/delete"
    for cascade in (False, True):
        response = client.post(delete, {"note": "Wrong source", "cascade": cascade})
        assert response.status_code == 409
        error = error_of(response)
        assert (error["code"], error["details"]) == ("has_dependents", {"field_verification": 1})
    assert client.item("evidence", evidence["id"])["deleted_at"] is None
    meta = client.item("project", project["id"])["field_meta"]["name_en"]
    assert (meta["verified"], meta["evidence_id"]) == ("verified", evidence["id"])
    client.ok(client.post(verify, {"field": "name_en", "status": "unverified"}))
    deleted = client.ok(client.post(delete, {"note": "Wrong source"}))
    assert deleted["item"]["deleted_at"] is not None


# --------------------------------------------------------------------------------------
# Bulk edit
# --------------------------------------------------------------------------------------


def test_bulk_edit_reports_per_item(client: ApiClient) -> None:
    projects = [client.create_project() for _ in range(4)]
    edited = client.update("project", projects[1], {"notes": "Changed before"})["item"]
    client.ok(client.post(f"/api/entities/project/{projects[2]['id']}/delete", {}))
    client.update("project", projects[3], {"status": "active"})
    unknown = "prj_01JBX3AAAAAAAAAAAAAAAAAAAA"
    body = client.ok(
        client.post(
            "/api/entities/project/bulk",
            {
                "ids": [*(project["id"] for project in projects), unknown],
                "set": {"status": "active"},
                "note": "Bulk example",
            },
        )
    )
    assert set(body) == {"batch_id", "results"}
    results = {result["id"]: result for result in body["results"]}
    assert results[projects[0]["id"]] == {
        "id": projects[0]["id"],
        "status": "updated",
        "version": 2,
        "error": None,
    }
    assert results[projects[1]["id"]]["status"] == "updated"
    assert results[projects[1]["id"]]["version"] == edited["version"] + 1
    assert results[projects[2]["id"]]["status"] == "entity_deleted"
    assert results[projects[2]["id"]]["version"] == 2
    assert results[projects[3]["id"]]["status"] == "unchanged"
    assert results[unknown]["status"] == "error"
    assert results[unknown]["error"]["code"] == "not_found"
    batch = client.ok(client.get("/api/revisions", {"batch_id": body["batch_id"]}))["items"]
    assert sorted((entry["entity_id"], entry["note"]) for entry in batch) == sorted(
        [(projects[0]["id"], "Bulk example"), (projects[1]["id"], "Bulk example")]
    )


def test_bulk_add_and_remove_on_list_fields(client: ApiClient) -> None:
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    codes = [t["code"] for t in next(v for v in listing if v["name"] == "policy_domain")["terms"]]
    project = client.create_project(policy_domains=[codes[0]])
    url = "/api/entities/project/bulk"
    ids = [project["id"]]
    body = client.ok(client.post(url, {"ids": ids, "add": {"policy_domains": codes[1:3]}}))
    assert body["results"][0]["status"] == "updated"
    assert client.item("project", project["id"])["fields"]["policy_domains"] == codes[:3]
    client.ok(client.post(url, {"ids": ids, "remove": {"policy_domains": [codes[0]]}}))
    assert client.item("project", project["id"])["fields"]["policy_domains"] == codes[1:3]


def test_bulk_requests_that_are_refused_as_a_whole(client: ApiClient) -> None:
    project = client.create_project()
    item = project["id"]
    many = [f"prj_{index:026d}" for index in range(501)]
    url = "/api/entities/project/bulk"
    cases: list[tuple[dict[str, Any], str]] = [
        ({"ids": [item], "set": {"name_en": "Example"}}, "set.name_en"),
        ({"ids": [item, item], "set": {"status": "active"}}, "ids[1]"),
        ({"ids": [item], "add": {"status": ["active"]}}, "add.status"),
        ({"ids": [item], "set": {"in_paper_scope": True}}, "set.scope_note"),
        ({"ids": [item], "set": {"verification_status": "verified"}}, "note"),
        ({"ids": [], "set": {"status": "active"}}, "ids"),
        ({"ids": many, "set": {"status": "active"}}, "ids"),
        ({"ids": [item]}, "set"),
        ({"ids": [7], "set": {"status": "active"}}, "ids[0]"),
        ({"set": {"status": "active"}}, "ids"),
        ({"items": [{"id": item}], "set": {"status": "active"}}, "items"),
    ]
    for body, path in cases:
        response = client.post(url, body)
        assert response.status_code == 400, body
        assert path in error_of(response)["details"], (path, error_of(response))
    assert client.item("project", project["id"])["version"] == 1


def test_bulk_scope_change_with_a_note(client: ApiClient) -> None:
    project = client.create_project()
    body = client.ok(
        client.post(
            "/api/entities/project/bulk",
            {
                "ids": [project["id"]],
                "set": {"in_paper_scope": True, "scope_note": "Synthetic reason."},
            },
        )
    )
    assert body["results"][0]["status"] == "updated"
    assert client.item("project", project["id"])["fields"]["in_paper_scope"] is True


def test_verified_fields_need_quoted_evidence(client: ApiClient) -> None:
    project = client.create_project()
    unquoted = client.create(
        "evidence",
        {"subject_id": project["id"], "target": "field:name_en", "url": "https://example.org/a"},
    )
    url = f"/api/entities/project/{project['id']}/verify-field"
    body = {"field": "name_en", "status": "verified"}
    response = client.post(url, body | {"evidence_id": unquoted["id"]})
    assert (response.status_code, error_of(response)["code"]) == (400, "evidence_required")
    assert "quote" in error_of(response)["message"]
    quoted = client.update("evidence", unquoted, {"quote": "Example quote."})["item"]
    client.ok(client.post(url, body | {"evidence_id": quoted["id"]}))
    response = client.patch(
        f"/api/entities/evidence/{quoted['id']}",
        {"changes": {"quote": None}},
    )
    assert error_of(response)["details"] == {
        "quote": ["A field is verified with this evidence; its verbatim quote cannot be removed"]
    }


def test_excluded_documents_need_an_exclusion_reason(client: ApiClient) -> None:
    document = client.create("document", {"title": "Example document"})
    url = f"/api/entities/document/{document['id']}"
    response = client.patch(url, {"changes": {"screening_status": "excluded"}})
    assert error_of(response)["details"] == {
        "screening_reason": ["is required when the document is excluded"]
    }
    changes = {"screening_status": "excluded", "screening_reason": "duplicate"}
    excluded = client.ok(client.patch(url, {"changes": changes}))["item"]
    assert excluded["fields"]["screening_reason"] == "duplicate"
    response = client.patch(url, {"changes": {"screening_status": "included"}})
    assert error_of(response)["details"] == {
        "screening_reason": ["is allowed only for excluded documents"]
    }
