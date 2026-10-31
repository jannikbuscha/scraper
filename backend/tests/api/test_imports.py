"""Tabular imports over HTTP (docs/API.md §7.9), with the real codebook and seed."""

from __future__ import annotations

from typing import Any

from tests.api.helpers import ApiClient, error_of


def _upload(client: ApiClient, body: bytes, filename: str) -> str:
    response = client.client.post(f"/api/uploads?filename={filename}", content=body)
    return str(client.ok(response, 201)["upload"]["id"])


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def _body(upload_id: str, **values: Any) -> dict[str, Any]:
    return {"upload_id": upload_id, "entity_type": "project", **values}


def test_preview_dry_run_run_and_history(client: ApiClient) -> None:
    project = client.create_project(name_en="Example project")
    upload_id = _upload(
        client,
        _csv("slug,notes", f"{project['fields']['slug']},Synthetic imported note"),
        "notes.csv",
    )
    preview = client.ok(client.post("/api/imports/preview", _body(upload_id)))
    assert preview["columns"] == ["slug", "notes"]
    assert preview["suggested_mapping"] == {"slug": "slug", "notes": "notes"}
    assert preview["key_fields"] == ["id", "slug"]
    mapping = preview["suggested_mapping"]
    plan = client.ok(
        client.post("/api/imports/dry-run", _body(upload_id, mapping=mapping, key_field="slug"))
    )["plan"]
    assert plan["stats"]["update"] == 1
    assert plan["rows"][0]["changes"] == {"notes": [None, "Synthetic imported note"]}
    body = client.ok(
        client.post(
            "/api/imports", _body(upload_id, mapping=mapping, key_field="slug", note="Synthetic")
        ),
        201,
    )
    run = body["import"]
    assert run["status"] == "done" and run["stats"]["update"] == 1
    assert body["result"]["rows"][0]["id"] == project["id"]
    item = client.item("project", project["id"])
    assert item["fields"]["notes"] == "Synthetic imported note"
    assert item["field_meta"]["notes"]["src"] == f"import:{run['file_label']}"
    changes = client.ok(client.get("/api/revisions", {"batch_id": run["id"]}))
    assert [entry["entity_id"] for entry in changes["items"]] == [project["id"]]
    history = client.ok(client.get("/api/imports"))
    assert history["total"] == 1 and history["items"][0]["id"] == run["id"]
    assert client.ok(client.get(f"/api/imports/{run['id']}"))["import"] == run


def test_a_manual_value_is_a_conflict_in_the_dry_run(client: ApiClient) -> None:
    project = client.create_project(name_en="Example project", notes="Person's note")
    upload_id = _upload(
        client, _csv("slug,notes", f"{project['fields']['slug']},Imported note"), "conflict.csv"
    )
    plan = client.ok(
        client.post(
            "/api/imports/dry-run",
            _body(upload_id, mapping={"slug": "slug", "notes": "notes"}, key_field="slug"),
        )
    )["plan"]
    assert plan["stats"]["conflicts"] == 1
    assert plan["rows"][0]["conflicts"] == [
        {"field": "notes", "current": "Person's note", "new": "Imported note", "reason": "manual"}
    ]


def test_validation_errors(client: ApiClient) -> None:
    upload_id = _upload(client, _csv("slug,notes", "example,note"), "v.csv")
    response = client.post(
        "/api/imports/dry-run", _body(upload_id, mapping={"notes": "canonical_url"})
    )
    assert response.status_code == 400
    assert set(error_of(response)["details"]) == {"mapping.notes"}
    response = client.post("/api/imports/preview", _body(upload_id, entity_type="evidence"))
    assert response.status_code == 400 and "entity_type" in error_of(response)["details"]
    response = client.post("/api/imports/preview", _body(upload_id, extra=True))
    assert response.status_code == 400
    pdf = _upload(client, b"%PDF-1.4 example", "file.pdf")
    response = client.post("/api/imports/preview", _body(pdf))
    assert response.status_code == 400
    assert error_of(response)["details"] == {"upload_id": ["upload a CSV or XLSX file"]}
    assert client.get("/api/imports/imp_unknown").status_code == 404
    assert client.get("/api/imports", {"page_size": 0}).status_code == 400
