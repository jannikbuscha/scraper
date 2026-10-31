"""Runs of C2 ``project_sites`` through the run framework (docs/COLLECTORS.md §8.2, §12.1):
on a fresh database with the real codebook and seed, whose projects' ``official_urls``
are the input, against the fixtures of ``backend/tests/fixtures/project_sites/`` (the replay
transport, with some hosts answered by the test); nothing reaches the network."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import httpx2
from sqlalchemy import select

from mdt.collectors.replay import REPLAY_EXTENSION, ReplayTransport
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.throttle import HostThrottle
from mdt.db.models import FetchLog, Project, RunMessage
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.collectors.conftest import FIXTURES, FakeClock
from tests.helpers import fields_of

__all__ = ["acceptance", "acceptance_template"]

COLLECTOR = "project_sites"
#: Input key → (final URL, publisher, the seed project whose official URL it is).
DOCUMENTS = {
    "url:https://usf.com.ua/": ("https://usf.com.ua/", "usf.com.ua", "usf"),
    "url:https://u24.gov.ua/": ("https://u24.gov.ua/", "u24.gov.ua", "united24"),
    "url:https://united24media.com/": (
        "https://united24media.com/",
        "united24media.com",
        "united24-media",
    ),
}
Answer = Callable[[httpx2.Request], httpx2.Response]


class PatchedReplay(ReplayTransport):
    """The fixtures, except for the hosts the test answers itself."""

    def __init__(self, answers: Mapping[str, Answer]) -> None:
        super().__init__([FIXTURES / COLLECTOR])
        self.answers = dict(answers)

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        answer = self.answers.get(request.url.host)
        if answer is None:
            return super().handle_request(request)
        response = answer(request)
        response.extensions[REPLAY_EXTENSION] = {
            "fixture": None,
            "retrieved_at": "2026-10-30T12:00:00.000000Z",
        }
        return response


def not_found(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(404, text="<html><body><h1>Example not found</h1></body></html>")


def challenge(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/robots.txt":
        return httpx2.Response(404)
    return httpx2.Response(
        403,
        text="<html><head><title>Just a moment...</title></head><body></body></html>",
        headers={"content-type": "text/html"},
    )


def run_with(acceptance: Acceptance, answers: Mapping[str, Answer]) -> str:
    """One run of C2 on the fixtures, with ``answers`` for some hosts."""
    transport = PatchedReplay(answers)
    with acceptance.db.session() as session:
        run_id = start_run(
            session, acceptance.settings, RunRequest(COLLECTOR, trigger="cli"), transport=transport
        )
    environment = RunEnvironment(transport=transport, clock=FakeClock(), throttle=HostThrottle())
    execute_run(acceptance.db.factory, acceptance.settings, run_id, environment=environment)
    return run_id


def projects(acceptance: Acceptance) -> dict[str, str]:
    """Seed key → project ID."""
    with acceptance.db.session() as session, read_transaction(session):
        return {
            str(row.seed_key): str(row.id)
            for row in session.execute(select(Project.seed_key, Project.id))
            if row.seed_key
        }


def messages(acceptance: Acceptance, run_id: str, codes: Iterable[str]) -> list[dict[str, Any]]:
    with acceptance.db.session() as session, read_transaction(session):
        return [
            {"code": row.code, "level": row.level, "url": row.url, "message": row.message}
            for row in session.scalars(
                select(RunMessage)
                .where(RunMessage.run_id == run_id, RunMessage.code.in_(list(codes)))
                .order_by(RunMessage.id)
            )
        ]


def fetched_hosts(acceptance: Acceptance, run_id: str) -> set[str]:
    with acceptance.db.session() as session, read_transaction(session):
        return set(session.scalars(select(FetchLog.host).where(FetchLog.run_id == run_id)))


def test_a_run_creates_a_document_per_official_url(acceptance: Acceptance) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR)
    row = acceptance.run_row(run_id)
    # digitalstate.gov.ua has no fixture (refused): partial, and the listing is incomplete.
    assert (row["status"], row["complete_listing"]) == ("partial", False)
    observations = acceptance.observations(COLLECTOR)
    ids = projects(acceptance)
    with acceptance.db.session() as session:
        for key, (url, publisher, project) in DOCUMENTS.items():
            document_id = observations[key]["subject_id"]
            assert document_id is not None
            document = fields_of(session, "document", document_id)
            assert (document["url"], document["publisher"]) == (url, publisher)
            assert (document["source_id"], document["external_id"]) == (COLLECTOR, None)
            assert document["doc_type"] == "project_page"
            assert document["extraction_method"] == "html"
            assert document["text_hash"] and document["published"] is None
            assert document["title"] == observations[key]["label"]
            stated = [link for link in document["links"] if link["subject_id"] == ids[project]]
            assert [(link["origin"], link["state"]) for link in stated] == [("auto", "suggested")]
        usf = fields_of(session, "document", observations["url:https://usf.com.ua/"]["subject_id"])
    assert (usf["title"], usf["language"], usf["license"]) == (
        "Фонд розвитку інновацій – Ukrainian Startup Fund",
        "uk",
        "unknown",  # "©" only: the default of sources.yaml
    )
    # The client-rendered shell and the refused URL are sighted, without a document.
    for key in ("url:https://winwin.gov.ua/", "url:https://digitalstate.gov.ua/"):
        assert observations[key]["subject_id"] is None
        assert observations[key]["last_seen_run"] == run_id
    [shell] = messages(acceptance, run_id, ["no_server_rendered_content"])
    assert (shell["level"], shell["url"]) == ("warning", "https://winwin.gov.ua/")
    # codeua.com is an excluded host (sources.yaml): never requested, not even robots.txt.
    assert "codeua.com" not in fetched_hosts(acceptance, run_id)
    assert not [key for key in observations if "codeua" in key]


def test_the_listing_is_complete_when_every_url_got_a_response(acceptance: Acceptance) -> None:
    run_id = run_with(acceptance, {"digitalstate.gov.ua": not_found})
    row = acceptance.run_row(run_id)
    # A 404 is a final response: the listing is complete, the run partial (http_error).
    assert (row["status"], row["complete_listing"]) == ("partial", True)
    [error] = messages(acceptance, run_id, ["http_error"])
    assert error["url"] == "https://digitalstate.gov.ua/"
    observation = acceptance.observations(COLLECTOR)["url:https://digitalstate.gov.ua/"]
    assert observation["subject_id"] is None and observation["last_seen_run"] == run_id


def test_an_official_url_removed_from_its_project_goes_missing(acceptance: Acceptance) -> None:
    run_with(acceptance, {"digitalstate.gov.ua": not_found})
    with acceptance.db.session() as session:
        apply_change(
            session,
            "project",
            projects(acceptance)["usf"],
            {"official_urls": []},
            Actor.ui(),
            note="Example removal",
        )
    second = run_with(acceptance, {"digitalstate.gov.ua": not_found})
    assert acceptance.run_row(second)["complete_listing"] is True
    observations = acceptance.observations(COLLECTOR)
    assert observations["url:https://usf.com.ua/"]["present"] is False
    assert observations["url:https://u24.gov.ua/"]["present"] is True
    assert "usf.com.ua" not in fetched_hosts(acceptance, second)
    assert acceptance.proposals(kind="possibly_discontinued") == []  # documents get none


def test_a_blocked_host_makes_the_run_partial_not_failed(acceptance: Acceptance) -> None:
    run_id = run_with(acceptance, {"usf.com.ua": challenge, "digitalstate.gov.ua": not_found})
    row = acceptance.run_row(run_id)
    assert (row["status"], row["error"]) == ("partial", None)  # no listing host
    [blocked] = messages(acceptance, run_id, ["blocked"])
    assert blocked["level"] == "error"
    observations = acceptance.observations(COLLECTOR)
    assert observations["url:https://usf.com.ua/"]["subject_id"] is None
    assert observations["url:https://u24.gov.ua/"]["subject_id"] is not None
    # The challenge page was a final response, so the listing is still complete.
    assert row["complete_listing"] is True


def test_limit_caps_the_urls_and_never_completes_the_listing(acceptance: Acceptance) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR, params={"limit": 1})
    row = acceptance.run_row(run_id)
    assert row["complete_listing"] is False
    # In canonical-URL order the first input URL is digitalstate.gov.ua.
    assert list(acceptance.observations(COLLECTOR)) == ["url:https://digitalstate.gov.ua/"]
