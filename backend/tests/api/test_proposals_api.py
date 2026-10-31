"""The Phase 2 endpoints of the review inbox, observations and merging (docs/API.md §7.4-
§7.6), plus the Phase 2 parts of /api/stats, entity details and the revision feed.
Proposals are raised by the reconciler from synthetic candidates (example.org)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.db.models import Proposal
from mdt.domain.reconcile import reconcile_candidate
from tests.api.helpers import ApiClient, error_of, project_data
from tests.conftest import Db
from tests.domain_p2.conftest import P2, StubScope, candidate

URL = "https://example.org/projects/api-example"
#: A collector of the real sources.yaml (the API checks collector names against it).
COLLECTOR = "ministry_projects"


@pytest.fixture
def p2(api_db: Db) -> P2:
    return P2(api_db, api_db.settings, api_db.factory)


def raise_update(p2: P2, client: ApiClient) -> tuple[dict[str, Any], StubScope, dict[str, Any]]:
    """A project with a manual description and an ``update_field`` proposal from a run."""
    item = client.create(
        "project", project_data(ministry_urls=[URL], description_uk="Manual example")
    )
    scope = p2.scope(collector=COLLECTOR)
    snapshot = p2.snapshot(scope.run_id, URL, source_id=COLLECTOR)
    with p2.session() as session:
        reconcile_candidate(
            session,
            scope,
            candidate(
                "project",
                "entry:api-example",
                snapshot,
                url=URL,
                fields={"description_uk": "Collected example"},
            ),
        )
    [proposal] = p2.proposals()
    return item, scope, proposal


def test_listing_and_reading_proposals(p2: P2, client: ApiClient) -> None:
    item, scope, proposal = raise_update(p2, client)
    page = client.ok(client.get("/api/proposals"))
    assert (page["total"], page["page"], page["page_size"]) == (1, 1, 50)
    [listed] = page["items"]
    assert listed["id"] == proposal["id"]
    assert (listed["live_value"], listed["current_value"], listed["proposed_value"]) == (
        "Manual example",
        "Manual example",
        "Collected example",
    )
    assert page["refs"][item["id"]]["label"] == "Example project"
    for params, total in (
        ({"kind": "update_field"}, 1),
        ({"kind": "create_event"}, 0),
        ({"subject_id": item["id"]}, 1),
        ({"run_id": scope.run_id}, 1),
        ({"field": "description_uk"}, 1),
        ({"state": "rejected"}, 0),
        ({"state": "all", "sort": "created_at"}, 1),
        ({"collector": "tagger"}, 0),
    ):
        assert client.ok(client.get("/api/proposals", params))["total"] == total, params
    for params in ({"state": "bogus"}, {"sort": "label"}, {"kind": "x"}, {"collector": "nope"}):
        response = client.get("/api/proposals", params)
        assert response.status_code == 400 and error_of(response)["code"] == "validation_error"
    detail = client.ok(client.get(f"/api/proposals/{proposal['id']}"))
    assert detail["proposal"]["id"] == proposal["id"] and detail["texts"] is None
    assert error_of(client.get("/api/proposals/prp_01JBX3EXAMPLE0000000000000"))["code"] == (
        "not_found"
    )
    summary = client.ok(client.get("/api/proposals/summary"))
    assert summary["open"] == 1 and summary["by_kind"] == {"update_field": 1}
    assert summary["by_collector"] == {COLLECTOR: 1} and summary["patterns"] == []
    stats = client.ok(client.get("/api/stats"))
    assert stats["open_proposals"] == 1 and set(stats["runs"]) == {"running", "last_finished"}
    detail_item = client.ok(client.get(f"/api/entities/project/{item['id']}"))["item"]
    assert detail_item["virtual"]["open_proposals"] == 1
    assert detail_item["virtual"]["open_proposals_by_field"] == {"description_uk": 1}
    [observation] = detail_item["observations"]
    assert (observation["key"], observation["bound_by"]) == ("entry:api-example", "auto")
    filtered = client.ok(client.get("/api/entities/project", {"f.open_proposals": "range:1.."}))
    assert [entry["id"] for entry in filtered["items"]] == [item["id"]]


def test_the_summary_reports_the_precision_of_each_event_pattern(p2: P2, client: ApiClient) -> None:
    """The precision of an event pattern is reported by the summary that the review inbox
    shows (docs/CODEBOOK.md §4, docs/COLLECTORS.md §7.7, docs/API.md §7.4): accepted and
    edited-and-accepted among the decided ``create_event`` proposals, null without a
    decision. The proposals come from the real event patterns of the codebook."""
    # Names without a word of any pattern ("Example Beta" would also match "beta").
    names = ["Example Aster", "Example Birch", "Example Cedar", "Example Dune", "Example Elm"]
    ids = {name: client.create("project", project_data(name_en=name))["id"] for name in names}
    sentences = [f"{name} went live today." for name in names[:4]]
    sentences.append("Example Elm was renamed.")
    url = "https://example.org/news/api-example"
    scope = p2.scope(collector="ministry_news")
    snapshot = p2.snapshot(scope.run_id, url, source_id="ministry_news")
    fields = {
        "title": "Example news",
        "url": url,
        "language": "en",
        "published": "2026-01-02",
        "published_basis": "stated_in_source",
    }
    with p2.session() as session:
        outcome = reconcile_candidate(
            session,
            scope,
            candidate(
                "document",
                "news:api-example",
                snapshot,
                url=url,
                fields=fields,
                text="\n".join(sentences),
                extraction_method="html",
            ),
        )
    assert outcome.action == "created", scope.messages
    rows = p2.proposals(Proposal.kind == "create_event")
    proposals = {row["subject_id"]: row["id"] for row in rows}
    assert len(rows) == len(names) and set(proposals) == set(ids.values())
    accepted, modified, rejected = (proposals[ids[name]] for name in names[:3])
    client.ok(client.post(f"/api/proposals/{accepted}/accept", {}))
    edited = {"values": {"description_en": "Edited example"}}
    decision = client.ok(client.post(f"/api/proposals/{modified}/accept", edited))
    assert decision["proposal"]["state"] == "accepted_modified"
    client.ok(client.post(f"/api/proposals/{rejected}/reject", {"note": "Not a launch"}))
    summary = client.ok(client.get("/api/proposals/summary"))
    assert summary["patterns"] == [
        {
            "pattern_id": "launch_en_launched",
            "open": 1,
            "accepted": 1,
            "accepted_modified": 1,
            "rejected": 1,
            "precision": pytest.approx(2 / 3),
        },
        {
            "pattern_id": "rebrand_en_renamed",
            "open": 1,
            "accepted": 0,
            "accepted_modified": 0,
            "rejected": 0,
            "precision": None,
        },
    ]


def test_accepting_and_rejecting(p2: P2, client: ApiClient) -> None:
    item, _, proposal = raise_update(p2, client)
    response = client.post(f"/api/proposals/{proposal['id']}/accept", {"bogus": 1})
    assert response.status_code == 400
    body = client.ok(
        client.post(
            f"/api/proposals/{proposal['id']}/accept",
            {"values": {"description_uk": "Edited example"}, "note": "Edited"},
        )
    )
    assert body["changed"] is True and body["result_id"] == item["id"]
    assert body["proposal"]["state"] == "accepted_modified" and len(body["revision_ids"]) == 1
    feed = client.ok(client.get("/api/revisions", {"proposal_id": proposal["id"]}))
    assert [entry["id"] for entry in feed["items"]] == body["revision_ids"]
    assert feed["items"][0]["proposal_id"] == proposal["id"]
    again = client.post(f"/api/proposals/{proposal['id']}/accept", {})
    assert again.status_code == 409 and error_of(again)["details"] == {"state": "accepted_modified"}
    # A new proposal for another value, then rejected.
    scope = p2.scope(collector=COLLECTOR)
    with p2.session() as session:
        reconcile_candidate(
            session,
            scope,
            candidate(
                "project",
                "entry:api-example",
                p2.snapshot(scope.run_id, URL),
                url=URL,
                fields={"description_uk": "Another example"},
            ),
        )
    [other] = [row for row in p2.proposals() if row["state"] == "open"]
    missing_note = client.post(f"/api/proposals/{other['id']}/reject", {})
    assert missing_note.status_code == 400
    rejected = client.ok(client.post(f"/api/proposals/{other['id']}/reject", {"note": "No"}))
    assert rejected["proposal"]["state"] == "rejected"


def test_bulk_decisions(p2: P2, client: ApiClient) -> None:
    _, _, proposal = raise_update(p2, client)
    body = client.ok(
        client.post(
            "/api/proposals/bulk",
            {"ids": [proposal["id"], "prp_01JBX3EXAMPLE0000000000000"], "action": "accept"},
        )
    )
    assert [result["status"] for result in body["results"]] == ["accepted", "error"]
    assert body["results"][1]["error"]["code"] == "not_found"
    invalid = client.post("/api/proposals/bulk", {"ids": [], "action": "accept"})
    assert invalid.status_code == 400
    duplicated = client.post(
        "/api/proposals/bulk",
        {"ids": [proposal["id"], proposal["id"]], "action": "reject", "note": "x"},
    )
    assert duplicated.status_code == 400


def test_listing_observations(p2: P2, client: ApiClient) -> None:
    item, _, _ = raise_update(p2, client)
    page = client.ok(client.get("/api/observations", {"collector": COLLECTOR}))
    [observation] = page["items"]
    assert set(observation) == {
        "id", "collector", "key", "entity_type", "subject_id", "bound_by", "bound_at",
        "external_id", "url", "label", "first_seen_at", "first_seen_run", "last_seen_at",
        "last_seen_run", "present", "missing_since_at", "missing_runs", "last_snapshot_id",
        "details",
    }  # fmt: skip
    assert page["refs"][item["id"]]["type"] == "project"
    for params, total in (
        ({"subject_id": item["id"]}, 1),
        ({"bound": "false"}, 0),
        ({"present": "true"}, 1),
        ({"q": "API-EXAMPLE"}, 1),
        ({"q": "nothing"}, 0),
        ({"entity_type": "document"}, 0),
    ):
        assert client.ok(client.get("/api/observations", params))["total"] == total, params
    assert client.get("/api/observations", {"present": "maybe"}).status_code == 400


def test_merge_preview_merge_and_unmerge(client: ApiClient) -> None:
    project = client.create("project", project_data())
    survivor = client.create("service", {"project_id": project["id"], "name_en": "Example kept"})
    merged = client.create("service", {"project_id": project["id"], "name_en": "Example gone"})
    base = f"/api/entities/service/{survivor['id']}"
    preview = client.ok(client.get(f"{base}/merge-preview", {"merged_id": merged["id"]}))
    assert preview["conflicts"] == [] and preview["repoint"]["event"] == 0
    assert {"name": "name_en", "survivor": "Example kept", "merged": "Example gone",
            "list": False, "default": "survivor"} in preview["fields"]  # fmt: skip
    assert client.get(f"{base}/merge-preview").status_code == 400
    body = client.ok(
        client.post(f"{base}/merge", {"merged_id": merged["id"], "fields": {"name_en": "merged"}})
    )
    assert body["item"]["fields"]["name_en"] == "Example gone" and body["merge_id"].startswith(
        "mrg_"
    )
    gone = client.ok(client.get(f"/api/entities/service/{merged['id']}"))["item"]
    assert gone["merged_into"] == survivor["id"] and gone["deleted_at"] is not None
    refused = client.post(f"/api/entities/service/{merged['id']}/undelete", {})
    assert refused.status_code == 409 and error_of(refused)["details"] == {"state": "merged"}
    restored = client.ok(
        client.post(f"/api/entities/service/{merged['id']}/unmerge", {"note": "No"})
    )
    assert restored["item"]["merged_into"] is None and restored["skipped"] == []
    assert (
        client.post(f"/api/entities/event/{merged['id']}/merge", {"merged_id": "x"}).status_code
        == 400
    )
    again = client.post(f"/api/entities/service/{merged['id']}/unmerge", {})
    assert again.status_code == 409 and error_of(again)["code"] == "invalid_state"


def test_a_merge_conflict_changes_nothing(client: ApiClient) -> None:
    project = client.create("project", project_data())
    survivor = client.create("service", {"project_id": project["id"], "name_en": "Example kept"})
    merged = client.create("service", {"project_id": project["id"], "name_en": "Example gone"})
    relation = client.create(
        "relation", {"from_id": survivor["id"], "to_id": merged["id"], "relation_type": "builds_on"}
    )
    response = client.post(
        f"/api/entities/service/{survivor['id']}/merge", {"merged_id": merged["id"]}
    )
    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "merge_conflict"
    assert [conflict["id"] for conflict in error["details"]["conflicts"]] == [relation["id"]]
    assert (
        client.ok(client.get(f"/api/entities/service/{merged['id']}"))["item"]["deleted_at"] is None
    )
