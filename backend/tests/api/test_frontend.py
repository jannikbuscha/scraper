"""Serving the built frontend (API §6): assets, root files, the SPA fallback, 503 without
a build, and path traversal attempts. The build is a synthetic directory."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mdt.app import create_app
from tests.api.conftest import api_settings
from tests.api.helpers import BASE_URL, call_asgi, error_of
from tests.conftest import Db

INDEX = b"<!doctype html><title>Example app</title><div id=root></div>"
SCRIPT = b'console.log("example");'


def make_build(root: Path) -> Path:
    """A synthetic build with root files, assets and asset symlinks pointing in and out."""
    dist = root / "dist"
    (dist / "assets" / "nested").mkdir(parents=True)
    (dist / "subdir").mkdir()
    (dist / "index.html").write_bytes(INDEX)
    (dist / "favicon.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    (dist / "subdir" / "page.html").write_bytes(b"not served")
    (dist / "assets" / "app-0a1b2c.js").write_bytes(SCRIPT)
    (dist / "assets" / "nested" / "chunk-3d4e.js").write_bytes(SCRIPT)
    outside = root / "outside-secret.txt"
    outside.write_bytes(b"secret outside the build")
    os.symlink(outside, dist / "assets" / "escape.js")
    os.symlink(dist / "assets" / "app-0a1b2c.js", dist / "assets" / "alias.js")
    return dist


@pytest.fixture
def built_app(api_db: Db) -> Iterator[FastAPI]:
    dist = make_build(api_db.root)
    app = create_app(api_settings(api_db.root, frontend_dist=dist))
    try:
        yield app
    finally:
        app.state.mdt.engine.dispose()


@pytest.fixture
def web(built_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(built_app, base_url=BASE_URL) as client:
        yield client


def test_the_spa_fallback_returns_index_html(web: TestClient) -> None:
    paths = ["/", "/projects", "/projects/prj_01JBX3AAAAAAAAAAAAAAAAAAAA?tab=history"]
    for path in [*paths, "/index.html", "/codebook/", "/docs"]:
        response = web.get(path)
        assert response.status_code == 200, path
        assert response.content == INDEX
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert response.headers["cache-control"] == "no-cache"


def test_head_requests(web: TestClient) -> None:
    response = web.head("/projects")
    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["content-length"] == str(len(INDEX))
    assert web.head("/assets/app-0a1b2c.js").status_code == 200


def test_root_files_are_served_by_exact_name(web: TestClient) -> None:
    response = web.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["cache-control"] == "no-cache"
    # Files below subdirectories are not root files: the SPA answers.
    assert web.get("/subdir/page.html").content == INDEX


def test_assets_are_served(web: TestClient) -> None:
    response = web.get("/assets/app-0a1b2c.js")
    assert (response.status_code, response.content) == (200, SCRIPT)
    assert response.headers["content-type"].startswith("text/javascript")
    assert web.get("/assets/nested/chunk-3d4e.js").content == SCRIPT
    assert web.get("/assets/alias.js").content == SCRIPT  # a symlink inside the assets


def test_assets_answer_conditional_requests(web: TestClient) -> None:
    etag = web.get("/assets/app-0a1b2c.js").headers["etag"]
    response = web.get("/assets/app-0a1b2c.js", headers={"If-None-Match": etag})
    assert (response.status_code, response.content) == (304, b"")


@pytest.mark.parametrize(
    "path", ["/assets/missing.js", "/assets", "/assets/", "/assets/escape.js", "/assets/nested"]
)
def test_missing_assets_are_404_never_index_html(web: TestClient, path: str) -> None:
    response = web.get(path)
    assert response.status_code == 404, path
    assert error_of(response)["code"] == "not_found"
    assert b"secret" not in response.content


def test_other_methods_on_non_api_paths_are_405(web: TestClient) -> None:
    for path in ("/", "/projects", "/assets/app-0a1b2c.js"):
        response = web.post(path, json={})
        assert (response.status_code, error_of(response)["code"]) == (405, "method_not_allowed")
        assert response.headers["allow"] == "GET, HEAD"


def test_unknown_api_paths_stay_404(web: TestClient) -> None:
    response = web.get("/api/projects")
    assert (response.status_code, error_of(response)["code"]) == (404, "not_found")
    response = web.get("/api")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/../x", INDEX),  # /%2e%2e/x, decoded by the server
        ("/../../../../etc/passwd", INDEX),
        ("//etc/passwd", INDEX),
        ("/..\\..\\outside-secret.txt", INDEX),
        ("/../outside-secret.txt", INDEX),
        ("/assets/../../data/app.db", None),  # /assets/..%2f..%2fdata%2fapp.db
        ("/assets/../index.html", None),
        ("/assets/../../outside-secret.txt", None),
        ("/assets//etc/passwd", None),
        ("/assets/%2e%2e/%2e%2e/outside-secret.txt", None),
        ("/assets/\x00.js", None),
    ],
)
def test_path_traversal_attempts(built_app: FastAPI, path: str, expected: bytes | None) -> None:
    result = call_asgi(built_app, "GET", path)
    assert b"secret" not in result.body and b"SQLite" not in result.body
    if expected is None:
        assert result.status == 404, (path, result.body)
    else:
        assert (result.status, result.body) == (200, expected), path


def test_traversal_through_the_test_client(web: TestClient) -> None:
    assert web.get("/assets/..%2f..%2fdata%2fapp.db").status_code == 404
    assert web.get("/assets/%2e%2e/%2e%2e/outside-secret.txt").status_code == 404
    response = web.get("/%2e%2e/x")
    assert (response.status_code, response.content) == (200, INDEX)


def test_without_a_build_non_api_paths_answer_503(api_db: Db) -> None:
    dist = api_db.root / "partial"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_bytes(SCRIPT)
    app = create_app(api_settings(api_db.root, frontend_dist=dist))
    try:
        with TestClient(app, base_url=BASE_URL) as client:
            for path in ("/", "/projects", "/assets/app.js", "/favicon.svg"):
                response = client.get(path)
                assert response.status_code == 503, path
                error = error_of(response)
                assert error["code"] == "frontend_not_built"
                assert "make build" in error["message"]
            assert client.get("/api/meta").status_code == 200
    finally:
        app.state.mdt.engine.dispose()
