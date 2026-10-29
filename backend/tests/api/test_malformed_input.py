"""Malformed input is a 400, never a 500 (API §1.2): unpaired surrogates in JSON bodies,
numbers beyond the 64-bit or float range, timestamps before the year 1000 or outside the
datetime range, control characters in search texts and out-of-range bulk versions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.api.helpers import ALICE, ApiClient, encode_author, error_of


def raw_write(client: ApiClient, method: str, path: str, body: str | bytes) -> Any:
    """Send ``body`` exactly as given (JSON text, so escapes such as ``\\ud800`` reach the
    server unchanged)."""
    return client.client.request(
        method,
        path,
        content=body.encode("utf-8") if isinstance(body, str) else body,
        headers={"X-Author": encode_author(ALICE), "Content-Type": "application/json"},
    )


def write_json(client: ApiClient, method: str, path: str, body: Any) -> Any:
    """Send ``body`` as JSON with ASCII escapes: an unpaired surrogate in a Python string
    becomes a ``\\udXXX`` escape, exactly what a client can send."""
    return raw_write(client, method, path, json.dumps(body))


def validation_details(response: Any) -> dict[str, list[str]]:
    assert response.status_code == 400, (response.status_code, response.text)
    error = error_of(response)
    assert error["code"] == "validation_error", error
    return dict(error["details"])


# --------------------------------------------------------------------------------------
# Unpaired surrogates
# --------------------------------------------------------------------------------------


def test_unpaired_surrogates_in_create_bodies(client: ApiClient) -> None:
    project = client.create_project()
    body = {"subject_id": project["id"], "body_md": "a\ud800b"}
    assert '"a\\ud800b"' in json.dumps(body)  # sent as an escape
    response = write_json(client, "POST", "/api/comments", body)
    assert list(validation_details(response)) == ["body_md"]
    data = {"slug": "s1", "name_en": "a\ud800", "in_paper_scope": False, "scope_note": "x"}
    response = write_json(client, "POST", "/api/entities/project", {"data": data})
    assert list(validation_details(response)) == ["data.name_en"]
    data = {"name_en": "ok", "aliases": [{"text": "a\ud800"}], "urls": ["https://e.org/\udfff"]}
    response = write_json(client, "POST", "/api/entities/organization", {"data": data})
    assert set(validation_details(response)) == {"data.aliases[0].text", "data.urls[0]"}
    # raw surrogate bytes (CESU-style), which json.loads decodes with "surrogatepass"
    response = raw_write(
        client,
        "POST",
        "/api/comments",
        b'{"subject_id": "' + project["id"].encode() + b'", "body_md": "hi \xed\xa0\xbd"}',
    )
    assert list(validation_details(response)) == ["body_md"]
    # a valid surrogate pair is an ordinary character
    comment = client.comment(project["id"], "Smile \U0001f600")
    assert comment["body_md"] == "Smile \U0001f600"


def test_unpaired_surrogates_in_patch_bodies(client: ApiClient) -> None:
    project = client.create_project()
    url = f"/api/entities/project/{project['id']}"
    cases: list[tuple[dict[str, Any], str]] = [
        ({"changes": {"name_en": "x\udc00"}}, "changes.name_en"),
        ({"changes": {"name_en": "ok"}, "note": "n\ud800"}, "note"),
        ({"changes": {"notes": "line\ud800"}}, "changes.notes"),
        ({"changes": {"official_urls": ["https://e.org/\ud800"]}}, "changes.official_urls[0]"),
        ({"changes": {"aliases": [{"text": "al\ud800"}]}}, "changes.aliases[0].text"),
    ]
    for body, path in cases:
        response = write_json(client, "PATCH", url, {"expected_version": 1, **body})
        assert list(validation_details(response)) == [path]
    term = client.list("vocabulary_term", **{"f.vocabulary": "eq:status"})["items"][0]
    term_url = f"/api/entities/vocabulary_term/{term['id']}"
    version = term["version"]
    value = {"expected_version": version, "changes": {"attributes": {"k": "v\udc00"}}}
    response = write_json(client, "PATCH", term_url, value)
    assert list(validation_details(response)) == ["changes.attributes.k"]
    key = {"expected_version": version, "changes": {"attributes": {"k\ud800": "v"}}}
    details = validation_details(write_json(client, "PATCH", term_url, key))
    assert list(details) == ["changes.attributes"]
    assert "key" in details["changes.attributes"][0]
    # nothing was written
    assert client.item("project", project["id"])["version"] == 1
    assert client.item("vocabulary_term", term["id"])["version"] == version


def test_unpaired_surrogates_in_bulk_and_action_bodies(client: ApiClient) -> None:
    project = client.create_project()
    bulk = "/api/entities/project/bulk"
    item = {"id": project["id"], "expected_version": 1}
    body: dict[str, Any] = {
        "items": [{"id": project["id"] + "\ud800", "expected_version": 1}],
        "set": {"status": "active"},
    }
    assert list(validation_details(write_json(client, "POST", bulk, body))) == ["items[0].id"]
    body = {"items": [item], "set": {"stat\ud800us": "active"}}
    assert list(validation_details(write_json(client, "POST", bulk, body))) == ["set"]
    body = {"items": [item], "add": {"beneficiaries": ["citizens"]}, "note": "x\ud800"}
    assert list(validation_details(write_json(client, "POST", bulk, body))) == ["note"]
    verify = {
        "expected_version": 1,
        "field": "name_en",
        "status": "verified",
        "evidence_id": "evd_\ud800",
    }
    response = write_json(
        client, "POST", f"/api/entities/project/{project['id']}/verify-field", verify
    )
    assert list(validation_details(response)) == ["evidence_id"]
    assert client.item("project", project["id"])["version"] == 1


# --------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "eq:9223372036854775808",
        "range:-9223372036854775809..",
        "eq:" + "9" * 5000,
    ],
)
def test_integer_filters_beyond_64_bits_are_bad_filters(client: ApiClient, value: str) -> None:
    response = client.get("/api/entities/project", {"f.open_comments": value})
    assert (response.status_code, error_of(response)["code"]) == (400, "bad_filter")


def test_number_filters_accept_large_bounds(client: ApiClient) -> None:
    assert client.list("project", **{"f.open_comments": "eq:9223372036854775807"})["total"] == 0
    large = "range:..1" + "0" * 30
    assert client.list("indicator", **{"f.value": large})["total"] == 0
    response = client.get("/api/entities/indicator", {"f.value": "range:..1e999"})
    assert error_of(response)["code"] == "bad_filter"


def test_body_numbers_beyond_the_float_range(client: ApiClient) -> None:
    project = client.create_project()
    subject = json.dumps(project["id"])
    prefix = '{"data": {"subject_id": ' + subject + ', "metric": "m", "value": '
    response = raw_write(client, "POST", "/api/entities/indicator", prefix + "1" + "0" * 400 + "}}")
    assert validation_details(response) == {"value": ["must be a finite number"]}
    # more digits than Python converts: the body itself cannot be parsed
    response = raw_write(
        client, "POST", "/api/entities/indicator", prefix + "1" + "0" * 5000 + "}}"
    )
    assert list(validation_details(response)) == ["body"]
    created = client.create(
        "indicator", {"subject_id": project["id"], "metric": "m", "value": 10_000_000_000}
    )
    assert created["fields"]["value"] == 1e10


# --------------------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------------------


def test_datetime_fields_with_early_years_and_overflowing_offsets(client: ApiClient) -> None:
    document = client.create(
        "document",
        {"title": "t", "url": "https://ts.example/1", "retrieved_at": "0999-01-01T00:00:00Z"},
    )
    assert document["fields"]["retrieved_at"] == "0999-01-01T00:00:00.000000Z"
    shifted = client.create(
        "document",
        {"title": "t", "url": "https://ts.example/2", "retrieved_at": "1000-01-01T00:10:00+00:30"},
    )
    assert shifted["fields"]["retrieved_at"] == "0999-12-31T23:40:00.000000Z"
    for value in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-01:00"):
        response = client.post(
            "/api/entities/document",
            {"data": {"title": "t", "url": "https://ts.example/3", "retrieved_at": value}},
        )
        assert list(validation_details(response)) == ["retrieved_at"]
    response = client.patch(
        f"/api/entities/document/{document['id']}",
        {"expected_version": 1, "changes": {"retrieved_at": "9999-12-31T23:59:59-01:00"}},
    )
    assert list(validation_details(response)) == ["retrieved_at"]
    project = client.create_project()
    evidence = client.create(
        "evidence",
        {
            "subject_id": project["id"],
            "target": "entity",
            "url": "https://example.org/e",
            "retrieved_at": "0999-06-01T00:00:00Z",
        },
    )
    assert evidence["fields"]["retrieved_at"] == "0999-06-01T00:00:00.000000Z"


def test_revision_feed_time_bounds_at_the_edges(client: ApiClient) -> None:
    total = client.ok(client.get("/api/revisions"))["total"]
    early = client.ok(client.get("/api/revisions", {"until": "0001-01-01T00:00:00Z"}))
    assert early["total"] == 0
    since = client.ok(client.get("/api/revisions", {"since": "0999-01-01T00:00:00+00:30"}))
    assert since["total"] == total
    for params in (
        {"since": "0001-01-01T00:00:00+14:00"},
        {"until": "9999-12-31T23:59:59-01:00"},
    ):
        details = validation_details(client.get("/api/revisions", params))
        assert list(details) == list(params)


# --------------------------------------------------------------------------------------
# Control characters in q
# --------------------------------------------------------------------------------------


def test_search_texts_with_nul_characters(client: ApiClient) -> None:
    project = client.create_project(name_en="Example zqxjnul project")
    client.create("document", {"title": "Example zqxjnul document"})
    client.comment(project["id"], "Example zqxjnul comment")
    paths = [
        "/api/entities/project",
        "/api/entities/service",
        "/api/entities/organization",
        "/api/entities/vocabulary_term",
        "/api/entities/document",
        "/api/comments",
        "/api/lookup",
    ]
    for path in paths:
        for q in ("a\x00b", "zqxjnul\x00", '"a\x00b"', "\x00"):
            response = client.get(path, {"q": q})
            assert response.status_code == 200, (path, q, response.text)
    found = client.list("project", q="zqxjnul\x00")["items"]
    assert [item["id"] for item in found] == [project["id"]]
    assert client.ok(client.get("/api/comments", {"q": "zqx\x00jnul"}))["total"] == 0
    facets = client.get("/api/entities/document/facets", {"field": "doc_type", "q": "a\x00b"})
    assert facets.status_code == 200
    export = client.get("/api/entities/project/export", {"q": "zqxjnul\x00"})
    assert export.status_code == 200
    assert project["id"] in export.text


# --------------------------------------------------------------------------------------
# Bulk versions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("version", [-5, 2**63, 2**80])
def test_bulk_versions_outside_the_64_bit_range(client: ApiClient, version: int) -> None:
    project = client.create_project()
    response = client.post(
        "/api/entities/project/bulk",
        {
            "items": [{"id": project["id"], "expected_version": version}],
            "set": {"status": "active"},
        },
    )
    assert list(validation_details(response)) == ["items[0].expected_version"]
    assert client.item("project", project["id"])["version"] == 1


def test_bulk_version_at_the_upper_bound_is_a_conflict(client: ApiClient) -> None:
    project = client.create_project()
    body = client.ok(
        client.post(
            "/api/entities/project/bulk",
            {
                "items": [{"id": project["id"], "expected_version": 2**63 - 1}],
                "set": {"status": "active"},
            },
        )
    )
    assert [result["status"] for result in body["results"]] == ["conflict"]
