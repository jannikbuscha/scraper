"""The request guard (API §1.1): host allowlist, same-origin fetch headers, author,
content type, origin, body and query size; checked before routing and before any body
byte is read."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mdt.api.guard import MAX_BODY_BYTES, MAX_QUERY_BYTES, HostAllowlist, parse_origin
from mdt.app import StartupError, create_app
from tests.api.conftest import api_settings
from tests.api.helpers import ALICE, BASE_URL, HOST, ApiClient, call_asgi, encode_author, error_of
from tests.conftest import Db

JSON = ("content-type", "application/json")
REQUESTED_WITH = ("x-requested-with", "mdt")
AUTHOR = ("x-author", encode_author(ALICE))
SAME_ORIGIN = ("origin", BASE_URL)
PLACEHOLDERS = {
    "{entity_type}": "project",
    "{entity_id}": "prj_01JBX3AAAAAAAAAAAAAAAAAAAA",
    "{comment_id}": "cmt_01JBX3AAAAAAAAAAAAAAAAAAAA",
}


def code_of(result: Any) -> str:
    """The error code of an :class:`AsgiResult` or a response."""
    body = result.body if hasattr(result, "body_read") else result.content
    return str(json.loads(body)["error"]["code"])


def unsafe_routes(app: FastAPI) -> list[tuple[str, str]]:
    """``(method, path)`` of every API route with a method other than GET/HEAD/OPTIONS."""
    routes = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted((route.methods or set()) - {"GET", "HEAD", "OPTIONS"}):
                path = route.path
                for placeholder, value in PLACEHOLDERS.items():
                    path = path.replace(placeholder, value)
                assert "{" not in path, path
                routes.append((method, path))
    return routes


# --------------------------------------------------------------------------------------
# Every unsafe route
# --------------------------------------------------------------------------------------

#: (missing or wrong header set, expected status, expected code)
GUARD_CASES: list[tuple[str, list[tuple[str, str]], int, str]] = [
    ("no headers", [], 403, "cross_origin_forbidden"),
    ("no X-Requested-With", [AUTHOR, JSON], 403, "cross_origin_forbidden"),
    ("cross-site fetch", [REQUESTED_WITH, AUTHOR, JSON, ("sec-fetch-site", "cross-site")], 403,
     "cross_origin_forbidden"),
    ("same-site fetch", [REQUESTED_WITH, AUTHOR, JSON, ("sec-fetch-site", "same-site")], 403,
     "cross_origin_forbidden"),
    ("no author", [REQUESTED_WITH, JSON], 400, "author_required"),
    ("reserved author", [REQUESTED_WITH, JSON, ("x-author", "seed")], 400, "author_invalid"),
    ("no content type", [REQUESTED_WITH, AUTHOR], 415, "unsupported_media_type"),
    ("form content type", [REQUESTED_WITH, AUTHOR, ("content-type", "text/plain")], 415,
     "unsupported_media_type"),
    ("foreign origin", [REQUESTED_WITH, AUTHOR, JSON, ("origin", "http://evil.example")], 403,
     "cross_origin_forbidden"),
    ("null origin", [REQUESTED_WITH, AUTHOR, JSON, ("origin", "null")], 403,
     "cross_origin_forbidden"),
    ("too large", [REQUESTED_WITH, AUTHOR, JSON, ("content-length", str(MAX_BODY_BYTES + 1))],
     413, "payload_too_large"),
]  # fmt: skip


def test_the_unsafe_routes_are_the_documented_writes(app: FastAPI) -> None:
    assert sorted(unsafe_routes(app)) == sorted(
        [
            ("POST", "/api/entities/project"),
            ("POST", "/api/entities/project/bulk"),
            ("PATCH", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA"),
            ("POST", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA/delete"),
            ("POST", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA/undelete"),
            ("POST", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA/verify-field"),
            ("POST", "/api/entities/project/prj_01JBX3AAAAAAAAAAAAAAAAAAAA/restore"),
            ("POST", "/api/comments"),
            ("PATCH", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA"),
            ("POST", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA/resolve"),
            ("POST", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA/reopen"),
            ("POST", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA/delete"),
            ("POST", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA/undelete"),
            ("POST", "/api/comments/cmt_01JBX3AAAAAAAAAAAAAAAAAAAA/restore"),
        ]
    )


@pytest.mark.parametrize(("case", "headers", "status", "code"), GUARD_CASES)
def test_every_unsafe_route_is_refused_before_its_handler_runs(
    app: FastAPI, case: str, headers: list[tuple[str, str]], status: int, code: str
) -> None:
    for method, path in unsafe_routes(app):
        result = call_asgi(app, method, path, headers, body=b"{}")
        assert (result.status, code_of(result)) == (status, code), (case, method, path)
        # The handler needs the body; it was never read, so no handler ran.
        assert not result.body_read, (case, method, path)


def test_with_every_header_the_request_reaches_the_handler(app: FastAPI) -> None:
    """Control for the test above: the same calls with valid headers read the body."""
    headers = [REQUESTED_WITH, AUTHOR, JSON, SAME_ORIGIN, ("sec-fetch-site", "same-origin")]
    for method, path in unsafe_routes(app):
        result = call_asgi(app, method, path, headers, body=b"{}")
        assert result.body_read, (method, path)
        assert result.status in (400, 404), (method, path, result.body)
        assert code_of(result) in ("validation_error", "not_found")


def test_writes_to_non_api_paths_are_guarded_too(app: FastAPI) -> None:
    result = call_asgi(app, "POST", "/projects", [], body=b"{}")
    assert (result.status, code_of(result), result.body_read) == (400, "author_required", False)
    result = call_asgi(app, "DELETE", "/projects", [AUTHOR, JSON])
    assert (result.status, code_of(result)) == (405, "method_not_allowed")


# --------------------------------------------------------------------------------------
# Host allowlist
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:8080", "127.0.0.1", "localhost", "LOCALHOST:3000", "localhost:80"],
)
def test_allowed_hosts_pass(app: FastAPI, host: str) -> None:
    assert call_asgi(app, "GET", "/api/health", host=host).status == 200


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "evil.example",
        "localhost.",  # exact match, as Starlette's TrustedHostMiddleware
        "localhost.evil.example",
        "evil-localhost",
        "127.0.0.1.evil.example",
        "[::1]:8080",
        "localhost:99999",
        "localhost:",
        "local host",
    ],
)
def test_other_hosts_are_refused(app: FastAPI, host: str | None) -> None:
    for path in ("/api/health", "/", "/assets/app.js"):
        result = call_asgi(app, "GET", path, host=host)
        assert (result.status, code_of(result)) == (400, "invalid_host"), (host, path)


def test_repeated_host_headers_are_refused(app: FastAPI) -> None:
    result = call_asgi(app, "GET", "/api/health", [("host", "localhost")])
    assert (result.status, code_of(result)) == (400, "invalid_host")


def test_forwarded_host_headers_are_never_read(app: FastAPI) -> None:
    forwarded = [("x-forwarded-host", "localhost"), ("forwarded", "host=localhost")]
    assert call_asgi(app, "GET", "/api/health", forwarded, host="evil.example").status == 400
    spoofed = [("x-forwarded-host", "evil.example"), ("forwarded", "host=evil.example")]
    assert call_asgi(app, "GET", "/api/health", spoofed).status == 200


def test_a_lone_star_disables_the_host_check_with_a_warning(
    api_db: Db, caplog: pytest.LogCaptureFixture
) -> None:
    settings = api_settings(api_db.root, allowed_hosts="*")
    with caplog.at_level(logging.WARNING, logger="mdt.api"):
        app = create_app(settings)
    try:
        assert any("ALLOWED_HOSTS" in record.message for record in caplog.records)
        assert call_asgi(app, "GET", "/api/health", host="anything.example").status == 200
    finally:
        app.state.mdt.engine.dispose()


@pytest.mark.parametrize(
    "value", ["", "*,localhost", "*.example.org", "localhost:8080", "[::1]", "http://localhost"]
)
def test_malformed_allowed_hosts_stop_the_start(api_db: Db, value: str) -> None:
    with pytest.raises(StartupError, match="ALLOWED_HOSTS"):
        create_app(api_settings(api_db.root, allowed_hosts=value))


def test_host_allowlist_parsing() -> None:
    allowlist = HostAllowlist.parse([" LocalHost ", "mdt.example.org"])
    assert allowlist.hosts == frozenset({"localhost", "mdt.example.org"})
    assert allowlist.allows("MDT.example.org") and not allowlist.allows("example.org")
    assert HostAllowlist.parse(["*"]).allow_any


# --------------------------------------------------------------------------------------
# Same-origin fetch headers on /api
# --------------------------------------------------------------------------------------


def test_api_reads_need_x_requested_with(raw_client: TestClient) -> None:
    response = raw_client.get("/api/meta")
    assert (response.status_code, error_of(response)["code"]) == (403, "cross_origin_forbidden")
    response = raw_client.get("/api/meta", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 403
    assert raw_client.get("/api/meta", headers={"X-Requested-With": "mdt"}).status_code == 200
    # Unknown API paths are refused the same way (no probing without the header).
    assert raw_client.get("/api/unknown").status_code == 403


def test_cross_site_image_requests_cannot_export(raw_client: TestClient) -> None:
    """An ``<img src=…/export>`` on another site sends no custom header."""
    response = raw_client.get("/api/entities/project/export", headers={"Sec-Fetch-Site": "none"})
    assert response.status_code == 403


def test_health_is_exempt_only_for_get(raw_client: TestClient) -> None:
    assert raw_client.get("/api/health").status_code == 200
    assert raw_client.head("/api/health").status_code == 403


@pytest.mark.parametrize(
    ("site", "status"),
    [("same-origin", 200), ("none", 200), ("same-site", 403), ("cross-site", 403), ("x", 403)],
)
def test_sec_fetch_site(raw_client: TestClient, site: str, status: int) -> None:
    headers = {"X-Requested-With": "mdt", "Sec-Fetch-Site": site}
    assert raw_client.get("/api/stats", headers=headers).status_code == status


def test_non_api_reads_need_no_fetch_headers(raw_client: TestClient) -> None:
    response = raw_client.get("/projects", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 503  # no frontend build in these tests


def test_preflights_always_fail(raw_client: TestClient) -> None:
    response = raw_client.options(
        "/api/entities/project",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-author,content-type,x-requested-with",
        },
    )
    assert response.status_code == 403
    assert not any(name.lower().startswith("access-control-") for name in response.headers)


def test_responses_never_carry_cors_headers(client: ApiClient) -> None:
    response = client.client.get("/api/meta", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200
    assert not any(name.lower().startswith("access-control-") for name in response.headers)


# --------------------------------------------------------------------------------------
# Author, content type, origin, sizes
# --------------------------------------------------------------------------------------


def _create(app: FastAPI, headers: list[tuple[str, str | bytes]]) -> Any:
    body = b'{"data": {"slug": "example-guard", "name_en": "Example", "scope_note": "Synthetic."}}'
    base: list[tuple[str, str | bytes]] = [REQUESTED_WITH, JSON]
    return call_asgi(app, "POST", "/api/entities/project", base + headers, body=body)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (b"", "author_invalid"),
        (b"%zzAlice", "author_invalid"),
        (b"Alice%", "author_invalid"),
        (b"%C3%28", "author_invalid"),  # not UTF-8
        ("Ålice".encode(), "author_invalid"),  # raw bytes instead of percent-encoding
        (b"seed", "author_invalid"),
        (b"SYSTEM", "author_invalid"),
        (b"collector%3Ac1", "author_invalid"),
        (b"Alice%2C%20Bob", "author_invalid"),
        (b"Alice%E2%80%AE", "author_invalid"),  # bidi override
        (b"%E2%80%8B", "author_invalid"),  # zero-width space only
        (encode_author("x" * 101).encode(), "author_invalid"),
    ],
)
def test_invalid_authors_are_refused(app: FastAPI, value: bytes, code: str) -> None:
    result = _create(app, [("x-author", value)])
    assert (result.status, code_of(result), result.body_read) == (400, code, False)


def test_a_repeated_author_header_is_refused(app: FastAPI) -> None:
    result = _create(app, [AUTHOR, ("x-author", encode_author("Bob Example"))])
    assert (result.status, code_of(result)) == (400, "author_invalid")


def test_authors_are_decoded_and_normalised(client: ApiClient) -> None:
    data = {"slug": "example-author", "name_en": "Example", "scope_note": "Synthetic."}
    item = client.create("project", data, author="  Тест   Приклад ")
    assert item["created_by"] == "Тест Приклад"
    assert item["field_meta"]["slug"]["src"] == "manual:Тест Приклад"


@pytest.mark.parametrize(
    ("content_type", "status"),
    [
        ("application/json", 201),
        ("application/json; charset=utf-8", 201),
        ("Application/JSON", 201),
        ("application/json-patch+json", 415),
        ("application/x-www-form-urlencoded", 415),
        ("multipart/form-data; boundary=x", 415),
        ("text/plain;charset=UTF-8", 415),
    ],
)
def test_content_type_must_be_json(app: FastAPI, content_type: str, status: int) -> None:
    body = b'{"data": {"slug": "example-ct", "name_en": "Example", "scope_note": "Synthetic."}}'
    headers: list[tuple[str, str | bytes]] = [
        REQUESTED_WITH,
        AUTHOR,
        ("content-type", content_type),
    ]
    result = call_asgi(app, "POST", "/api/entities/project", headers, body=body)
    assert result.status == status, result.body


@pytest.mark.parametrize(
    ("host", "origin", "status"),
    [
        (HOST, "http://127.0.0.1:8080", 201),
        ("localhost", "http://localhost", 201),
        ("localhost", "http://localhost:80", 201),
        ("localhost:80", "http://localhost", 201),
        ("localhost", "https://localhost:443", 201),
        ("localhost:8080", "http://LOCALHOST.:8080", 201),
        ("localhost:8080", "http://localhost:8081", 403),
        ("localhost:8080", "https://localhost", 403),
        ("localhost", "https://localhost:80", 403),
        (HOST, "http://evil.example", 403),
        (HOST, "null", 403),
        (HOST, "http://127.0.0.1:8080/", 403),
        (HOST, "http://user@127.0.0.1:8080", 403),
        (HOST, "ftp://127.0.0.1:8080", 403),
        (HOST, "http://[::1]:8080", 403),
        (HOST, "not an origin", 403),
    ],
)
def test_origin_must_match_the_host(app: FastAPI, host: str, origin: str, status: int) -> None:
    result = call_asgi(
        app,
        "POST",
        "/api/entities/project",
        [REQUESTED_WITH, AUTHOR, JSON, ("origin", origin)],
        body=b'{"data": {"slug": "example-origin", "name_en": "Example", "scope_note": "S."}}',
        host=host,
    )
    assert result.status == status, result.body


def test_origin_parsing() -> None:
    assert parse_origin("HTTP://Example.ORG.:80") == ("http", "example.org")
    assert parse_origin("https://example.org:8443") == ("https", "example.org:8443")
    assert parse_origin("http://example.org:0") is None
    assert parse_origin("null") is None


def test_a_declared_oversized_body_is_refused_before_reading(app: FastAPI) -> None:
    headers = [REQUESTED_WITH, AUTHOR, JSON, ("content-length", str(MAX_BODY_BYTES + 1))]
    result = call_asgi(app, "POST", "/api/comments", headers, body=b"{}")
    assert (result.status, code_of(result), result.body_read) == (413, "payload_too_large", False)


def test_a_streamed_oversized_body_is_refused_while_reading(app: FastAPI) -> None:
    body = b'{"subject_id": "' + b"x" * MAX_BODY_BYTES + b'"}'
    result = call_asgi(app, "POST", "/api/comments", [REQUESTED_WITH, AUTHOR, JSON], body=body)
    assert (result.status, code_of(result)) == (413, "payload_too_large")


def test_a_body_at_the_limit_is_accepted(client: ApiClient) -> None:
    padding = " " * (MAX_BODY_BYTES - 200)
    body = '{"data": {"slug": "example-big", "name_en": "Example", "scope_note": "S."}}' + padding
    response = client.client.post(
        "/api/entities/project",
        content=body.encode(),
        headers={"X-Author": encode_author(ALICE), "Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text


def test_long_query_strings_are_refused(client: ApiClient) -> None:
    ok = "q=" + "a" * (MAX_QUERY_BYTES - 2)
    assert client.client.get(f"/api/stats?{ok}").status_code == 200
    response = client.client.get(f"/api/stats?{ok}a")
    assert (response.status_code, error_of(response)["code"]) == (414, "uri_too_long")


def test_websockets_are_refused(raw_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), raw_client.websocket_connect("/api/meta"):
        pass
