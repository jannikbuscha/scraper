"""The error envelope (API §1.2) and the security headers on every response (API §6)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from mdt.api.errors import error_response
from mdt.api.headers import SECURITY_HEADERS
from mdt.app import create_app
from mdt.domain.errors import ValidationError
from tests.api.helpers import BASE_URL, ApiClient, call_asgi, error_of
from tests.conftest import Db

SECRET = "SELECT secret FROM /etc/passwd"


def assert_security_headers(headers: Any) -> None:
    for name, value in SECURITY_HEADERS:
        assert headers.get(name) == value, name


# --------------------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------------------


def test_security_headers_on_api_responses_and_errors(client: ApiClient) -> None:
    responses = [
        client.get("/api/meta"),
        client.get("/api/health"),
        client.get("/api/entities/unknown"),
        client.get("/api/entities/project", {"f.nope": "eq:1"}),
        client.post("/api/entities/project", {"data": {}}),
        client.client.put("/api/entities/project", json={}, headers={"X-Author": "Alice"}),
        client.client.get("/api/meta", headers={"Host": "evil.example"}),
        client.client.get("/projects"),
        client.client.post("/api/comments", json={}),
    ]
    statuses = [response.status_code for response in responses]
    assert statuses == [200, 200, 404, 400, 400, 405, 400, 503, 400]
    for response in responses:
        assert_security_headers(response.headers)


def test_the_csp_has_no_inline_script_allowance() -> None:
    csp = dict(SECURITY_HEADERS)["Content-Security-Policy"]
    script = next(part for part in csp.split(";") if part.strip().startswith("script-src"))
    assert script.split() == ["script-src", "'self'"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp


def test_security_headers_on_internal_errors(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mdt.api.meta.entity_stats", _boom)
    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as client:
        response = client.get("/api/stats", headers={"X-Requested-With": "mdt"})
    assert response.status_code == 500
    assert_security_headers(response.headers)


def test_guard_rejections_carry_the_security_headers(app: FastAPI) -> None:
    result = call_asgi(app, "GET", "/api/meta", host="evil.example")
    assert result.status == 400
    assert_security_headers({name.title(): value for name, value in result.headers.items()})


# --------------------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------------------


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError(f"unexpected failure: {SECRET}")


def test_unexpected_errors_are_500_with_a_request_id_and_no_details(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("mdt.api.meta.entity_stats", _boom)
    with (
        caplog.at_level(logging.ERROR, logger="mdt.api"),
        TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as client,
    ):
        response = client.get("/api/stats", headers={"X-Requested-With": "mdt"})
    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "internal_error"
    request_id = error["details"]["request_id"]
    assert re.fullmatch(r"[0-9a-f]{16}", request_id)
    assert set(error["details"]) == {"request_id"}
    assert "secret" not in response.text and "Traceback" not in response.text
    logged = [record for record in caplog.records if request_id in record.getMessage()]
    assert logged and logged[0].exc_info is not None
    assert SECRET in str(logged[0].exc_info[1])


def test_unique_integrity_errors_become_unique_violation(
    client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unique_failure(*_args: Any, **_kwargs: Any) -> Any:
        orig = sqlite3.IntegrityError("UNIQUE constraint failed: project.slug")
        raise IntegrityError("INSERT …", {}, orig)

    monkeypatch.setattr("mdt.api.meta.entity_stats", unique_failure)
    response = client.get("/api/stats")
    assert response.status_code == 409
    assert error_of(response) | {"message": ""} == {
        "code": "unique_violation",
        "message": "",
        "details": {"field": "slug", "existing": None},
    }


def test_other_integrity_errors_are_internal_errors(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fk_failure(*_args: Any, **_kwargs: Any) -> Any:
        raise IntegrityError("INSERT …", {}, sqlite3.IntegrityError("FOREIGN KEY failed"))

    monkeypatch.setattr("mdt.api.meta.entity_stats", fk_failure)
    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as client:
        response = client.get("/api/stats", headers={"X-Requested-With": "mdt"})
    assert (response.status_code, error_of(response)["code"]) == (500, "internal_error")
    assert "FOREIGN" not in response.text


def test_a_locked_database_is_503_database_busy(
    api_db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A long write transaction elsewhere (e.g. a maintenance command) used to turn UI
    # writes into "500 Internal error" after the busy timeout.
    monkeypatch.setattr("mdt.db.engine.BUSY_TIMEOUT_MS", 100)
    app = create_app(api_db.settings)
    locker = sqlite3.connect(api_db.root / "app.db", isolation_level=None)
    try:
        with TestClient(app, base_url=BASE_URL, headers={"X-Requested-With": "mdt"}) as raw:
            client = ApiClient(raw)
            project = client.create_project()
            locker.execute("BEGIN IMMEDIATE")
            body = {"expected_version": 1, "changes": {"notes": "Synthetic"}}
            response = client.patch(f"/api/entities/project/{project['id']}", body)
            assert response.status_code == 503
            assert error_of(response)["code"] == "database_busy"
            assert response.headers["retry-after"] == "5"
            assert_security_headers(response.headers)
            comment = client.post("/api/comments", {"subject_id": project["id"], "body_md": "x"})
            assert error_of(comment)["code"] == "database_busy"
            # readers are not blocked (WAL)
            assert client.list("project", q="Example")["total"] >= 1
            locker.execute("ROLLBACK")
            updated = client.update("project", project, {"notes": "Synthetic"})
            assert updated["item"]["version"] == 2  # nothing was written while locked
    finally:
        locker.close()
        app.state.mdt.engine.dispose()


def test_pool_timeouts_are_503_and_other_database_errors_500(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def pool_exhausted(*_args: Any, **_kwargs: Any) -> Any:
        raise PoolTimeoutError("QueuePool limit of size 5 overflow 10 reached")

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("SELECT …", {}, sqlite3.OperationalError("no such table: x"))

    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as client:
        monkeypatch.setattr("mdt.api.meta.entity_stats", pool_exhausted)
        response = client.get("/api/stats", headers={"X-Requested-With": "mdt"})
        assert (response.status_code, error_of(response)["code"]) == (503, "database_busy")
        assert response.headers["retry-after"] == "5"
        monkeypatch.setattr("mdt.api.meta.entity_stats", broken)
        response = client.get("/api/stats", headers={"X-Requested-With": "mdt"})
        assert (response.status_code, error_of(response)["code"]) == (500, "internal_error")
        assert "no such table" not in response.text


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/api/entities/unknown", "not_found"),
        ("/api/entities/comment", "not_found"),
        ("/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA", "not_found"),
        ("/api/entities/project/not-an-id", "not_found"),
        ("/api/nothing/here", "not_found"),
        ("/api/entities/project/", "not_found"),
        ("/api/revisions/999999", "not_found"),
        ("/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA", "not_found"),
    ],
)
def test_not_found(client: ApiClient, path: str, code: str) -> None:
    response = client.get(path)
    assert (response.status_code, error_of(response)["code"]) == (404, code)


@pytest.mark.parametrize(
    ("method", "path", "allow"),
    [
        ("DELETE", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA", "GET, PATCH"),
        ("PUT", "/api/entities/project", "GET, POST"),
        ("PUT", "/api/revisions/authors", "GET"),
        # Also the path of an item with the ID "bulk": both routes are listed.
        ("DELETE", "/api/entities/project/bulk", "GET, PATCH, POST"),
        ("PATCH", "/api/comments", "GET, POST"),
    ],
)
def test_wrong_methods_are_405_listing_every_allowed_method(
    client: ApiClient, method: str, path: str, allow: str
) -> None:
    response = client.write(method, path)
    assert (response.status_code, error_of(response)["code"]) == (405, "method_not_allowed")
    assert response.headers["allow"] == allow


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ({}, "data"),
        ({"data": []}, "data"),
        ({"data": {}, "note": 5}, "note"),
        ({"data": {}, "extra": SECRET}, "extra"),
    ],
)
def test_body_validation_errors_are_400_with_paths_only(
    client: ApiClient, body: dict[str, Any], path: str
) -> None:
    response = client.post("/api/entities/project", body)
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert list(error["details"]) == [path]
    assert all(isinstance(message, str) for message in error["details"][path])
    assert SECRET not in response.text


def test_versions_are_strict_integers(client: ApiClient) -> None:
    project = client.create_project()
    url = f"/api/entities/project/{project['id']}"
    for version in ("1", 1.0, True, None, -1, 2**63):
        response = client.patch(url, {"expected_version": version, "changes": {}})
        assert response.status_code == 400, version
        assert list(error_of(response)["details"]) == ["expected_version"]


def test_invalid_json_is_a_validation_error(client: ApiClient) -> None:
    response = client.client.post(
        "/api/entities/project",
        content=b'{"data": {"name_en": "' + SECRET.encode() + b'"',
        headers={"X-Author": "Alice", "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert error_of(response) == {
        "code": "validation_error",
        "message": "Invalid input",
        "details": {"body": ["JSON decode error"]},
    }


def test_error_envelopes_can_always_be_encoded() -> None:
    # A path may repeat a key the client sent; an unpaired surrogate in it must not turn
    # the 400 into a 500 while the response is encoded as UTF-8.
    response = error_response(ValidationError({"set.k\ud800": ["bad \udc00 value"]}))
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["details"] == {"set.k\ufffd": ["bad \ufffd value"]}


def test_non_utf8_bodies_are_a_validation_error(client: ApiClient) -> None:
    response = client.client.post(
        "/api/entities/project",
        content=b'{"data": "\xff"}',
        headers={"X-Author": "Alice", "Content-Type": "application/json"},
    )
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")


def test_query_and_path_validation_errors_are_400(client: ApiClient) -> None:
    project = client.create_project()
    base = f"/api/entities/project/{project['id']}"
    response = client.get(f"{base}/diff", {"from": "x", "to": "1"})
    assert response.status_code == 400
    assert list(error_of(response)["details"]) == ["from"]
    response = client.get(f"{base}/diff", {"to": "1"})
    assert list(error_of(response)["details"]) == ["from"]
    response = client.get(f"{base}/revisions/abc")
    assert (response.status_code, list(error_of(response)["details"])) == (400, ["version"])
    response = client.get("/api/revisions/0")
    assert (response.status_code, list(error_of(response)["details"])) == (400, ["revision_id"])


def test_bad_filters_and_sorts(client: ApiClient) -> None:
    response = client.get("/api/entities/project", {"f.unknown_field": "eq:x"})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_filter")
    response = client.get("/api/entities/project", {"sort": "aliases"})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_sort")
    response = client.get("/api/entities/project", {"page_size": "501"})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")


def test_openapi_matches_the_error_contract(client: ApiClient) -> None:
    # FastAPI generates "422 HTTPValidationError"; the API answers 400 with the envelope.
    schema = client.ok(client.get("/api/openapi.json"))
    text = json.dumps(schema)
    assert '"422"' not in text and "HTTPValidationError" not in text
    envelope_ref = {"$ref": "#/components/schemas/ErrorEnvelope"}
    assert "ErrorEnvelope" in schema["components"]["schemas"]
    operations = [
        (path, method, operation)
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    ]
    assert len(operations) > 30
    for path, method, operation in operations:
        responses = operation["responses"]
        names = {(p["in"], p["name"]) for p in operation.get("parameters", [])}
        for status in ("400", "500"):
            content = responses[status]["content"]["application/json"]["schema"]
            assert content == envelope_ref, (path, method, status)
        if path == "/api/health":
            assert ("header", "X-Requested-With") not in names
            continue
        assert {"403", "503"} <= set(responses), (path, method)
        assert ("header", "X-Requested-With") in names, (path, method)
        if method in ("post", "patch"):
            assert {"409", "413", "415"} <= set(responses), (path, method)
            assert ("header", "X-Author") in names, (path, method)
        else:
            assert ("header", "X-Author") not in names, (path, method)
        if "{" in path:
            assert "404" in responses, (path, method)
    export = schema["paths"]["/api/entities/{entity_type}/export"]["get"]["responses"]
    assert "429" in export
    assert "docs/API.md is authoritative" in schema["info"]["description"]


def test_openapi_is_under_api_and_the_docs_are_off(client: ApiClient, app: FastAPI) -> None:
    assert app.debug is False
    schema = client.ok(client.get("/api/openapi.json"))
    assert "/api/entities/{entity_type}" in schema["paths"]
    # Swagger, ReDoc and the root OpenAPI path do not exist: these are SPA paths (503
    # without a build), never documentation.
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.client.get(path)
        assert response.status_code == 503, path
        assert error_of(response)["code"] == "frontend_not_built"
