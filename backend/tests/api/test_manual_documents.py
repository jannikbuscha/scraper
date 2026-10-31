"""Uploads (docs/API.md §7.7) and manual documents (§7.8) over HTTP.

Fetches run in replay mode (``COLLECTOR_REPLAY_DIR`` with synthetic fixtures on
example.org), so no request leaves the machine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from mdt.app import create_app
from tests.api.conftest import api_settings
from tests.api.helpers import BASE_URL, ApiClient, error_of
from tests.conftest import Db

FIXTURE_TIME = "2026-10-29T12:00:00.000000Z"
PAGE = "https://example.org/reports/annual"
HTML = (
    "<html><head><title>Example annual report</title></head><body><h1>Example annual report</h1>"
    "<p>Це приклад тексту звіту. Він написаний українською мовою, щоб мова визначалася "
    "правильно навіть разом з англійською назвою сторінки.</p></body></html>"
).encode()


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: httpx2.HTTPTransport, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"tests must not reach the network: {request.url}")

    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", refuse)


def _write_fixture(directory: Path, name: str, url: str, body: bytes = HTML) -> None:
    """A replay fixture (HTTP 200) for ``url``."""
    (directory / f"{name}.html").write_bytes(body)
    meta = {
        "fixture": name,
        "body": f"{name}.html",
        "url": url,
        "final_url": url,
        "redirects": [],
        "status": 200,
        "retrieved_at": FIXTURE_TIME,
        "content_type": "text/html; charset=utf-8",
        "headers": {"content-type": "text/html; charset=utf-8"},
    }
    (directory / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _replay_dir(root: Path) -> Path:
    directory = root / "replay"
    directory.mkdir()
    _write_fixture(directory, "annual", PAGE)
    return directory


@pytest.fixture
def client(api_db: Db, tmp_path: Path) -> Iterator[ApiClient]:
    settings = api_settings(api_db.root, collector_replay_dir=_replay_dir(tmp_path))
    with TestClient(create_app(settings), base_url=BASE_URL) as test_client:
        yield ApiClient(test_client)


def _upload(client: ApiClient, body: bytes, filename: str | None) -> httpx2.Response:
    query = "" if filename is None else f"?filename={filename}"
    return client.client.post(
        f"/api/uploads{query}", content=body, headers={"content-type": "application/octet-stream"}
    )


def test_an_upload_returns_the_snapshot_and_suggested_values(client: ApiClient) -> None:
    body = client.ok(_upload(client, HTML, "reports/annual.html"), 201)
    upload = body["upload"]
    assert upload["via"] == "upload" and upload["source_id"] == "manual"
    assert upload["filename"] == "annual.html" and upload["content_type"] == "text/html"
    assert upload["size"] == len(HTML) and upload["run_id"] is None
    assert body["suggested"] == {
        "title": "Example annual report",
        "language": "uk",
        "publisher": None,
        "extraction_method": "html",
        "char_count": body["suggested"]["char_count"],
        "warnings": [],
    }
    stored = client.client.get(f"/api/snapshots/{upload['id']}/body")
    assert stored.status_code == 200 and stored.content == HTML


@pytest.mark.parametrize(
    ("body", "filename", "path"),
    [(HTML, None, "filename"), (HTML, "", "filename"), (b"", "a.txt", "body")],
)
def test_upload_validation(client: ApiClient, body: bytes, filename: str | None, path: str) -> None:
    response = _upload(client, body, filename)
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_error" and path in error["details"]


def _create(client: ApiClient, **values: Any) -> httpx2.Response:
    return client.post("/api/documents/manual", values)


def test_a_document_from_an_upload(client: ApiClient) -> None:
    upload = client.ok(_upload(client, HTML, "annual.html"), 201)["upload"]
    body = client.ok(
        _create(
            client,
            snapshot_id=upload["id"],
            title="Example annual report",
            url="https://example.org/reports/annual.html",
            retrieved_at="2026-10-30T10:00:00Z",
            language="uk",
            doc_type="report",
            note="Added by hand",
        ),
        201,
    )
    item = body["item"]
    assert body["warnings"] == [] and isinstance(body["revision_id"], int)
    fields = item["fields"]
    assert fields["source_id"] == "manual" and fields["raw_snapshot_id"] == upload["id"]
    assert fields["extraction_method"] == "html"
    assert fields["text"].startswith("Example annual report")
    assert item["field_meta"]["title"]["src"] == "manual"


def test_creating_needs_a_known_manual_snapshot_and_strict_bodies(client: ApiClient) -> None:
    response = _create(client, snapshot_id="raw_unknown", title="Example")
    assert response.status_code == 400 and "snapshot_id" in error_of(response)["details"]
    response = _create(client, snapshot_id="raw_unknown", title="Example", extra=1)
    assert response.status_code == 400
    response = _create(client, title="Example")
    assert response.status_code == 400


def test_a_fetched_page_and_the_document_created_from_it(client: ApiClient) -> None:
    body = client.ok(client.post("/api/documents/fetch", {"url": PAGE}), 201)
    snapshot = body["snapshot"]
    assert snapshot["via"] == "replay" and snapshot["source_id"] == "manual"
    assert snapshot["fetched_at"] == FIXTURE_TIME
    assert body["suggested"]["publisher"] == "example.org"
    created = client.ok(
        _create(client, snapshot_id=snapshot["id"], title=body["suggested"]["title"]), 201
    )
    fields = created["item"]["fields"]
    assert (fields["url"], fields["retrieved_at"]) == (PAGE, FIXTURE_TIME)
    # The URL is now taken: a second fetch is refused before any request.
    again = client.post("/api/documents/fetch", {"url": PAGE + "/"})
    assert again.status_code == 409
    error = error_of(again)
    assert error["code"] == "unique_violation"
    assert error["details"]["existing"]["id"] == created["item"]["id"]


def test_a_url_without_fixture_is_a_failed_fetch(client: ApiClient) -> None:
    response = client.post("/api/documents/fetch", {"url": "https://example.org/missing"})
    assert response.status_code == 502
    error = error_of(response)
    assert error["code"] == "fetch_failed" and set(error["details"]) == {"reason", "status"}
    assert error["details"] == {"reason": "http_error", "status": None}


#: URLs that break the URL rule (DATA_MODEL §1.2), or a capture URL without an http(s) original.
INVALID_URLS = [
    "ftp://example.org/reports/annual",
    "https://user:secret@example.org/reports/annual",
    "https://example.org/reports/annual report",
    "not a url",
    "https://web.archive.org/web/20200102030405/example.org/reports/annual",
]


@pytest.mark.parametrize("url", INVALID_URLS)
def test_an_invalid_url_is_refused_before_anything_is_fetched(
    client: ApiClient, api_db: Db, url: str
) -> None:
    """docs/API.md §7.8 and docs/COLLECTORS.md §10.3: ``400 validation_error`` on ``url``,
    not ``502 fetch_failed``; no request is made and no snapshot is stored."""
    response = client.post("/api/documents/fetch", {"url": url})
    assert response.status_code == 400
    error = error_of(response)
    assert error["code"] == "validation_error" and set(error["details"]) == {"url"}
    with api_db.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM raw_snapshot")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM fetch_log")).scalar() == 0


def test_an_invalid_url_is_refused_before_the_contact_address_is_needed(api_db: Db) -> None:
    """The URL is checked first, also outside replay mode without ``CONTACT_EMAIL``."""
    with TestClient(create_app(api_settings(api_db.root)), base_url=BASE_URL) as test_client:
        response = ApiClient(test_client).post("/api/documents/fetch", {"url": INVALID_URLS[0]})
    assert response.status_code == 400
    assert error_of(response)["code"] == "validation_error"


def test_a_trap_path_is_a_failed_fetch(client: ApiClient, tmp_path: Path) -> None:
    """A valid URL that the polite client refuses (``/cdn-cgi/…``, docs/COLLECTORS.md §4.1)
    is a failed fetch with the reason ``http_error``, not an invalid URL, even though the
    replay directory could answer it."""
    url = "https://example.org/cdn-cgi/l/email-protection"
    _write_fixture(tmp_path / "replay", "trap", url)
    response = client.post("/api/documents/fetch", {"url": url})
    assert response.status_code == 502
    error = error_of(response)
    assert error["code"] == "fetch_failed"
    assert error["details"] == {"reason": "http_error", "status": None}


def test_fetching_without_a_contact_address_outside_replay_mode(api_db: Db) -> None:
    with TestClient(create_app(api_settings(api_db.root)), base_url=BASE_URL) as test_client:
        client = ApiClient(test_client)
        response = client.post("/api/documents/fetch", {"url": PAGE})
    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "collector_unavailable"
    assert error["details"] == {"reason": "contact_email_missing"}
