"""Runs of C5 ``wayback`` through the run framework (docs/COLLECTORS.md §8.5, §12.1): the
real codebook and seed plus the C5 setup of §12.1 (a test sources file with the prefix
``example.org/projects/`` and synthetic projects and services, ``wayback_helpers``), against
the synthetic fixtures of ``backend/tests/fixtures/wayback/`` (the replay transport, with
some URLs answered by the test). Nothing reaches the network.

The seed projects' own URLs have no fixture: their single-URL queries are refused, so these
runs end ``partial`` without a complete listing. Assertions concern the synthetic subjects.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import select

from mdt.collectors.replay import REPLAY_EXTENSION, ReplayTransport
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.store import SnapshotMeta, SnapshotStore
from mdt.collectors.throttle import HostThrottle
from mdt.collectors.wayback import UNAVAILABLE, prefix_query, url_query
from mdt.db.models import Event, Evidence, FetchLog, RawSnapshot
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.revisions import soft_delete
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.collectors.conftest import FIXTURES, FakeClock, fixture_path
from tests.collectors.wayback_helpers import TEST_PREFIX, create_subjects, use_test_sources

__all__ = ["acceptance", "acceptance_template"]

DIRECTORY = FIXTURES / "wayback"
FIRST_PAGE = prefix_query(TEST_PREFIX, 5000)
SERVICE_ONE = url_query("https://example.org/services/example-one")
SERVICE_TWO = url_query("https://example.org/services/example-two")
Answer = Callable[[httpx2.Request], httpx2.Response]


class PatchedReplay(ReplayTransport):
    """The fixtures of ``directory``, except the URLs the test answers itself; records
    every requested URL."""

    def __init__(self, directory: Path, answers: Mapping[str, Answer] | None = None) -> None:
        super().__init__([directory])
        self.answers = dict(answers or {})
        self.requested: list[str] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requested.append(url)
        answer = self.answers.get(url)
        if answer is None:
            return super().handle_request(request)
        response = answer(request)
        response.extensions[REPLAY_EXTENSION] = {
            "fixture": None,
            "retrieved_at": "2026-10-30T12:00:00.000000Z",
        }
        return response


def status(code: int, body: bytes = b"") -> Answer:
    return lambda request: httpx2.Response(code, content=body)


def run_wayback(
    acceptance: Acceptance, transport: ReplayTransport, params: Mapping[str, Any] | None = None
) -> str:
    """Start and execute one C5 run on ``transport``."""
    request = RunRequest("wayback", params=dict(params or {}), trigger="cli")
    with acceptance.db.session() as session:
        run_id = start_run(session, acceptance.settings, request, transport=transport)
    environment = RunEnvironment(transport=transport, clock=FakeClock(), throttle=HostThrottle())
    execute_run(acceptance.db.factory, acceptance.settings, run_id, environment=environment)
    return run_id


@pytest.fixture
def subjects(acceptance: Acceptance) -> dict[str, str]:
    """The C5 setup of docs/COLLECTORS.md §12.1; slug or service name → ID."""
    use_test_sources(acceptance)
    return create_subjects(acceptance)


def events(acceptance: Acceptance, subject_id: str) -> list[dict[str, Any]]:
    """The ``first_archived`` events of a subject (deleted ones included), oldest first,
    each with its evidence rows."""
    table, evidence = Event.__table__, Evidence.__table__
    with acceptance.db.session() as session, read_transaction(session):
        rows = [
            dict(row)
            for row in session.execute(
                select(table)
                .where(table.c.subject_id == subject_id, table.c.event_type == "first_archived")
                .order_by(table.c.created_at, table.c.id)
            ).mappings()
        ]
        for row in rows:
            row["evidence"] = [
                dict(item)
                for item in session.execute(
                    select(evidence).where(evidence.c.subject_id == row["id"])
                ).mappings()
            ]
    return rows


def archive_proposals(acceptance: Acceptance, subject_id: str) -> list[dict[str, Any]]:
    return [
        proposal
        for proposal in acceptance.proposals(kind="create_event", subject_id=subject_id)
        if proposal["payload"]["event"]["event_type"] == "first_archived"
    ]


def snapshot_url(acceptance: Acceptance, raw_snapshot_id: str) -> str | None:
    with acceptance.db.session() as session, read_transaction(session):
        row = session.get(RawSnapshot, raw_snapshot_id)
        assert row is not None
        return row.url


def requested(acceptance: Acceptance, run_id: str) -> list[str]:
    """The content URLs a run requested (or was refused), in order."""
    with acceptance.db.session() as session, read_transaction(session):
        return list(
            session.scalars(
                select(FetchLog.url)
                .where(FetchLog.run_id == run_id, FetchLog.purpose == "content")
                .order_by(FetchLog.id)
            )
        )


# --------------------------------------------------------------------------------------
# Run 1: events and proposals
# --------------------------------------------------------------------------------------


def test_exact_matches_create_events_with_evidence(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY))
    expected = {
        "example-alpha": (
            "2018-05-10",
            "20180510000000",
            "http://www.example.org/projects/technologies/example-alpha/",
        ),
        # 2021-03-01 22:30 UTC is already 2 March in Kyiv.
        "example-beta": (
            "2021-03-02",
            "20210301223000",
            "https://example.org/projects/business/example-beta",
        ),
        "example-gamma": (
            "2020-01-02",
            "20200102030405",
            "https://example.org/projects/technologies/example-gamma",
        ),
        "Example service One": (
            "2019-04-05",
            "20190405060708",
            "https://example.org/services/example-one",
        ),
        "Example service Two": (
            "2020-01-01",
            "20191231230000",
            "https://example.org/services/example-two",
        ),
    }
    for name, (day, timestamp, original) in expected.items():
        (event,) = events(acceptance, subjects[name])
        assert (event["date_start"], event["date_end"], event["date_precision"]) == (
            day,
            day,
            "day",
        )
        assert event["date_basis"] == "archive_upper_bound"
        assert event["date_text"] == f"{timestamp} {original}"
        assert event["description_en"] == (
            f"Earliest capture in the Wayback Machine (CDX, status 200) of {original}"
        )
        assert event["created_by"] == "collector:wayback"
        assert event["verification_status"] == "unverified"
        (evidence,) = event["evidence"]
        assert evidence["target"] == "entity"
        assert evidence["archive_url"] == f"https://web.archive.org/web/{timestamp}/{original}"
        assert evidence["url"] == snapshot_url(acceptance, evidence["raw_snapshot_id"])
        assert evidence["url"].startswith("https://web.archive.org/cdx/search/cdx?url=")
        assert json.loads(evidence["quote"])[1:3] == [timestamp, original]
    assert acceptance.run_row(run_id)["stats"]["extra"]["captures_mapped"] == 8


def test_slug_and_domain_root_matches_become_proposals(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_wayback(acceptance, PatchedReplay(DIRECTORY))
    alpha = archive_proposals(acceptance, subjects["example-alpha"])
    assert sorted(item["payload"]["event"]["date_text"] for item in alpha) == [
        "20150101000000 http://example.com/",  # the official URL, a domain root
        "20170301000000 http://example.org/projects/regions/example-alpha",  # other rubric
    ]
    (beta,) = archive_proposals(acceptance, subjects["example-beta"])  # pre-relaunch slug
    assert beta["payload"]["event"]["date"] == "2016-07-04"
    assert beta["payload"]["evidence"]["archive_url"] == (
        "https://web.archive.org/web/20160704000000/http://example.org/projects/example-beta"
    )
    assert beta["quote"] == json.dumps(
        [
            "org,example)/projects/example-beta",
            "20160704000000",
            "http://example.org/projects/example-beta",
            "200",
            "text/html",
        ]
    )
    assert archive_proposals(acceptance, subjects["example-gamma"]) == []
    assert all(item["state"] == "open" and item["collector"] == "wayback" for item in alpha)


def test_every_queried_url_and_urlkey_is_observed_unbound(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY))
    observations = acceptance.observations("wayback")
    alpha = observations["url:example.org/projects/technologies/example-alpha"]
    assert alpha["subject_id"] is None
    assert alpha["details"] == {
        "earliest": "20180510000000",
        "original": "http://www.example.org/projects/technologies/example-alpha/",
        "subject_ids": [subjects["example-alpha"]],
    }
    assert observations["url:example.org/projects/business"]["details"]["subject_ids"] == []
    assert observations["url:example.org/projects/page/2"]["details"]["subject_ids"] == []
    for key, url in [
        ("url:example.org", "https://www.example.org/"),  # answered with []
        ("url:example.org/about", "https://example.org/about"),  # header only
    ]:
        assert observations[key]["url"] == url
        assert observations[key]["details"]["earliest"] is None
    assert {observation["last_seen_run"] for observation in observations.values()} == {run_id}


def test_the_prefix_pages_come_first_then_the_single_urls(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY))
    urls = requested(acceptance, run_id)
    resume = "org%2Cexample%29%2Fprojects%2Fexample-beta+20160704000000%21"
    assert urls[:2] == [FIRST_PAGE, f"{FIRST_PAGE}&resumeKey={resume}"]
    synthetic = [url for url in urls[2:] if "example." in url.split("&", 1)[0]]
    assert synthetic == [
        url_query("https://example.com/"),
        url_query("https://www.example.org/"),
        url_query("https://example.org/about"),
        SERVICE_ONE,
        SERVICE_TWO,
    ]
    row = acceptance.run_row(run_id)
    # The seed projects' URLs have no fixture: refused, so the run is partial.
    assert row["status"] == "partial" and not row["complete_listing"]
    assert row["stats"]["extra"]["cdx_queries"] == len(urls)


# --------------------------------------------------------------------------------------
# Later runs
# --------------------------------------------------------------------------------------


def test_an_earlier_capture_adds_a_second_event_and_keeps_the_first(
    acceptance: Acceptance, subjects: dict[str, str], tmp_path: Path
) -> None:
    run_wayback(acceptance, PatchedReplay(DIRECTORY))
    variant = tmp_path / "wayback_variant"
    shutil.copytree(DIRECTORY, variant)
    body = variant / "synthetic_cdx_extra_columns.json"
    body.write_text(body.read_text("utf-8").replace("20190405060708", "20170102030405"), "utf-8")
    run_wayback(acceptance, PatchedReplay(variant))
    first, second = events(acceptance, subjects["Example service One"])
    assert (first["date_start"], first["deleted_at"]) == ("2019-04-05", None)
    assert (second["date_start"], second["deleted_at"]) == ("2017-01-02", None)
    assert len(second["evidence"]) == 1


def test_a_deleted_event_is_not_recreated(acceptance: Acceptance, subjects: dict[str, str]) -> None:
    run_wayback(acceptance, PatchedReplay(DIRECTORY))
    (event,) = events(acceptance, subjects["example-gamma"])
    with acceptance.db.session() as session:
        soft_delete(session, "event", event["id"], Actor.ui(), note="Example: not a capture")
    run_wayback(acceptance, PatchedReplay(DIRECTORY))
    (still,) = events(acceptance, subjects["example-gamma"])
    assert still["id"] == event["id"] and still["deleted_at"] is not None
    assert archive_proposals(acceptance, subjects["example-gamma"]) == []


def test_a_url_the_stored_robots_txt_disallows_is_never_queried(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    body = b"User-agent: *\nDisallow: /services/example-two\n"
    with acceptance.db.session() as session:
        SnapshotStore(acceptance.settings.raw_path).put(
            session,
            body,
            SnapshotMeta(
                source_id="manual",
                via="replay",
                url="https://example.org/robots.txt",
                final_url="https://example.org/robots.txt",
                http_status=200,
                fetched_at="2026-10-30T12:00:00.000000Z",
                headers={"content-type": "text/plain"},
            ),
        )
    transport = PatchedReplay(DIRECTORY)
    run_id = run_wayback(acceptance, transport)
    assert SERVICE_ONE in transport.requested
    assert SERVICE_TWO not in transport.requested
    assert SERVICE_TWO not in requested(acceptance, run_id)
    assert acceptance.run_row(run_id)["stats"]["extra"]["robots_skipped"] == 1
    assert events(acceptance, subjects["Example service Two"]) == []


def test_limit_stops_after_that_many_queries(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY), {"limit": 1})
    assert requested(acceptance, run_id) == [FIRST_PAGE]
    row = acceptance.run_row(run_id)
    assert row["stats"]["extra"]["cdx_queries"] == 1 and not row["complete_listing"]


class NoCapturesElsewhere(PatchedReplay):
    """The synthetic fixtures; every other CDX query is answered without captures."""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url.startswith("https://web.archive.org/cdx/") and url not in self.index:
            self.answers.setdefault(url, status(200, b"[]"))
        return super().handle_request(request)


def test_a_run_with_every_query_answered_completes_the_listing(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    first = run_wayback(acceptance, NoCapturesElsewhere(DIRECTORY))
    row = acceptance.run_row(first)
    assert (row["status"], row["complete_listing"]) == ("succeeded", True)
    with acceptance.db.session() as session:
        soft_delete(session, "project", subjects["example-gamma"], Actor.ui(), note="Example")
    second = run_wayback(acceptance, NoCapturesElsewhere(DIRECTORY))
    observations = acceptance.observations("wayback")
    # Gamma's official URL is no longer queried: missing after a complete run.
    assert observations["url:example.org/about"]["present"] is False
    assert observations["url:example.org/services/example-one"]["last_seen_run"] == second
    assert acceptance.run_row(second)["complete_listing"]


# --------------------------------------------------------------------------------------
# Availability: unavailable is never "no captures"
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({FIRST_PAGE: status(503)}, id="first-request-503"),
        pytest.param(
            {
                FIRST_PAGE: status(
                    429, fixture_path("wayback", "availability_429.html").read_bytes()
                )
            },
            id="first-request-429",
        ),
        pytest.param({"https://web.archive.org/robots.txt": status(403)}, id="robots-blocked"),
        pytest.param({"https://web.archive.org/robots.txt": status(500)}, id="robots-unavailable"),
    ],
)
def test_wayback_unavailable_fails_the_run(
    acceptance: Acceptance, subjects: dict[str, str], answers: Mapping[str, Answer]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY, answers))
    row = acceptance.run_row(run_id)
    assert (row["status"], row["error"]) == ("failed", UNAVAILABLE)
    assert acceptance.observations("wayback") == {}
    assert events(acceptance, subjects["example-alpha"]) == []


def test_a_later_failure_makes_the_run_partial(
    acceptance: Acceptance, subjects: dict[str, str]
) -> None:
    run_id = run_wayback(acceptance, PatchedReplay(DIRECTORY, {SERVICE_ONE: status(503)}))
    row = acceptance.run_row(run_id)
    assert row["status"] == "partial" and row["error"] is None
    assert events(acceptance, subjects["Example service One"]) == []
    assert "url:example.org/services/example-one" not in acceptance.observations("wayback")
    assert len(events(acceptance, subjects["Example service Two"])) == 1
