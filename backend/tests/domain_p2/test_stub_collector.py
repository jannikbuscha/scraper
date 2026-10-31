"""A test-only collector fed through the real run framework (``ctx.reconcile``): a second
run against the same responses creates no record, revision or proposal (DoD 3), and a
manual value wins over the collector's (DoD 5: the difference becomes an ``update_field``
proposal; accept, edit & accept and reject behave as in docs/DATA_MODEL.md §16.4).

The site is a synthetic JSON listing served by ``httpx2.MockTransport``; nothing reaches
the network."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest

from mdt.collectors import registry
from mdt.collectors.base import Candidate, Evidence, RunContext
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.throttle import HostThrottle
from mdt.db.models import CollectorRun, DocumentText, Project, Proposal, Revision
from mdt.db.session import create_session_factory, read_transaction
from mdt.domain.actor import Actor
from mdt.domain.proposal_actions import accept_proposal, reject_proposal
from mdt.domain.revisions import apply_change
from tests.collectors.conftest import TEST_EMAIL, FakeClock, Site
from tests.collectors.stubs import Behaviour, StubCollector, write_sources
from tests.conftest import Db, make_settings
from tests.domain_p2.conftest import P2, PROJECTS_DECLARATION
from tests.helpers import create_project, load

LISTING = "https://example.org/listing.json"
ENTRIES = [
    {"slug": "alpha", "caption": "Example caption alpha"},
    {"slug": "beta", "caption": "Example caption beta"},
    {"slug": "gamma", "caption": "Example caption gamma"},
]


def entry_url(slug: str) -> str:
    return f"https://example.org/projects/{slug}"


def listing(entries: list[dict[str, str]]) -> bytes:
    return json.dumps({"entries": entries}).encode("utf-8")


@dataclass
class Options:
    """How the next run behaves: whether it completes its listing, writes an error-level
    message (the run ends ``partial``) or is cancelled after the listing."""

    complete: bool = True
    error: bool = False
    cancel: bool = False


def listing_behaviour(options: Options, cancel: threading.Event) -> Behaviour:
    """Read the listing and reconcile one project candidate per entry."""

    def behaviour(ctx: RunContext) -> None:
        result = ctx.client.get(LISTING)
        assert result.snapshot is not None
        snapshot = result.snapshot
        for entry in json.loads(snapshot.body)["entries"]:
            ctx.reconcile(
                Candidate(
                    entity_type="project",
                    key=f"entry:{entry['slug']}",
                    evidence=Evidence(raw_snapshot_id=snapshot.raw_snapshot_id, source_url=LISTING),
                    url=entry_url(entry["slug"]),
                    fields={"description_uk": entry["caption"]},
                )
            )
        ctx.count("pages_parsed")
        if options.error:
            ctx.message("error", "parse_error", "synthetic parse error", url=LISTING)
        if options.complete:
            ctx.listing_complete()
        if options.cancel:
            cancel.set()

    return behaviour


@dataclass
class Env:
    p2: P2
    site: Site
    options: Options
    cancel: threading.Event

    def run(self, expected: str = "succeeded") -> str:
        transport = httpx2.MockTransport(self.site)
        with self.p2.session() as session:
            run_id = start_run(
                session, self.p2.settings, RunRequest("stub", trigger="cli"), transport=transport
            )
        environment = RunEnvironment(
            transport=transport, clock=FakeClock(), throttle=HostThrottle()
        )
        self.cancel.clear()
        status = execute_run(
            self.p2.factory, self.p2.settings, run_id, cancel=self.cancel, environment=environment
        )
        assert status == expected
        return run_id

    def counts(self) -> dict[str, int]:
        return {
            "projects": self.p2.count(Project),
            "revisions": self.p2.count(Revision),
            "proposals": self.p2.count(Proposal),
            "texts": self.p2.count(DocumentText),
        }

    def stats(self, run_id: str) -> dict[str, Any]:
        with self.p2.session() as session, read_transaction(session):
            row = session.get(CollectorRun, run_id)
            assert row is not None
            return dict(row.stats)


@pytest.fixture
def env(db: Db, tmp_path: Path, p2_codebook: Path, seed_dir: Path) -> Iterator[Env]:
    settings = make_settings(
        db.root,
        p2_codebook,
        seed_dir,
        sources_file=write_sources(tmp_path),
        contact_email=TEST_EMAIL,
    )
    options, cancel = Options(), threading.Event()
    registry.register(
        "stub",
        StubCollector(
            DECLARATION={"project": PROJECTS_DECLARATION},
            behaviour=listing_behaviour(options, cancel),
        ),
    )
    try:
        p2 = P2(db, settings, create_session_factory(db.engine, settings))
        yield Env(p2, Site({LISTING: listing(ENTRIES)}), options, cancel)
    finally:
        registry.unregister("stub")


def seed_projects(env: Env) -> dict[str, str]:
    with env.p2.session() as session:
        return {
            entry["slug"]: create_project(
                session,
                Actor.seed(),
                name_en=f"Example {entry['slug']}",
                ministry_urls=[entry_url(entry["slug"])],
            ).entity_id
            for entry in ENTRIES
        }


def test_a_second_run_writes_no_record_revision_or_proposal(env: Env) -> None:
    projects = seed_projects(env)
    env.run()
    with env.p2.session() as session:
        assert load(session, "project", projects["alpha"])["description_uk"] == (
            "Example caption alpha"
        )
    before = env.counts()
    second = env.run()
    assert env.counts() == before
    stats = env.stats(second)
    assert (stats["entities_created"], stats["entities_updated"], stats["revisions"]) == (0, 0, 0)
    assert stats["proposals_opened"] == 0 and stats["items_seen"] == 3
    for entry in ENTRIES:
        observation = env.p2.observation("stub", f"entry:{entry['slug']}")
        assert observation is not None and observation["last_seen_run"] == second


def test_manual_values_win_and_the_difference_is_proposed(env: Env) -> None:
    projects = seed_projects(env)
    first = env.run()
    with env.p2.session() as session:
        entry = load(session, "project", projects["alpha"])["field_meta"]["description_uk"]
    assert (entry["src"], entry["locked"]) == (f"collector:stub@{first}", False)
    assert entry["raw_snapshot_ids"] and len(entry["raw_snapshot_ids"]) == 1
    with env.p2.session() as session:
        for slug in ("alpha", "beta", "gamma"):
            apply_change(
                session,
                "project",
                projects[slug],
                {"description_uk": f"Manual {slug}"},
                Actor.ui(),
                note="Corrected",
            )
    second = env.run()
    with env.p2.session() as session:
        alpha = load(session, "project", projects["alpha"])
    assert alpha["description_uk"] == "Manual alpha"
    assert alpha["field_meta"]["description_uk"]["src"] == "manual"
    proposals = {row["subject_id"]: row for row in env.p2.proposals()}
    assert len(proposals) == 3
    assert {row["proposed_value"] for row in proposals.values()} == {
        entry["caption"] for entry in ENTRIES
    }
    with env.p2.session() as session:
        accept_proposal(session, proposals[projects["alpha"]]["id"])
        accept_proposal(
            session, proposals[projects["beta"]]["id"], values={"description_uk": "Edited beta"}
        )
        reject_proposal(session, proposals[projects["gamma"]]["id"], "The manual text is right")
    with env.p2.session() as session:
        alpha = load(session, "project", projects["alpha"])
        beta = load(session, "project", projects["beta"])
        gamma = load(session, "project", projects["gamma"])
    assert alpha["description_uk"] == "Example caption alpha"
    meta = alpha["field_meta"]["description_uk"]
    assert (meta["src"], meta["by"], meta["locked"]) == (f"collector:stub@{second}", "user", True)
    assert (
        meta["raw_snapshot_ids"]
        == proposals[projects["alpha"]]["payload"]["field_snapshots"]["description_uk"]
    )
    assert (beta["description_uk"], beta["field_meta"]["description_uk"]["src"]) == (
        "Edited beta",
        "manual",
    )
    assert gamma["description_uk"] == "Manual gamma"
    states = {row["subject_id"]: row["state"] for row in env.p2.proposals()}
    assert states == {
        projects["alpha"]: "accepted",
        projects["beta"]: "accepted_modified",
        projects["gamma"]: "rejected",
    }
    before = env.counts()
    env.run()  # nothing is proposed again for the three decided branches
    assert env.counts() == before


def test_possibly_discontinued_only_after_complete_runs(env: Env) -> None:
    projects = seed_projects(env)
    env.run()
    env.site.routes[LISTING] = listing(ENTRIES[:2])  # gamma leaves the listing

    def gamma() -> dict[str, Any]:
        observation = env.p2.observation("stub", "entry:gamma")
        assert observation is not None
        return observation

    env.options.complete = False  # incremental runs never mark keys as missing
    env.run()
    assert (gamma()["present"], gamma()["missing_runs"]) == (True, 0)
    env.options.complete, env.options.cancel = True, True  # nor do cancelled runs
    env.run(expected="cancelled")
    assert gamma()["missing_runs"] == 0
    env.options.cancel, env.options.error = False, True  # a partial run with a complete listing
    env.run(expected="partial")
    assert (gamma()["present"], gamma()["missing_runs"]) == (False, 1)
    assert env.p2.proposals() == []
    env.options.error = False
    env.run()
    [proposal] = env.p2.proposals()
    assert (proposal["kind"], proposal["subject_id"]) == (
        "possibly_discontinued",
        projects["gamma"],
    )
    env.site.routes[LISTING] = listing(ENTRIES)  # back in the listing
    env.run()
    [proposal] = env.p2.proposals()
    assert proposal["state"] == "superseded"
