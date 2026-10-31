"""Collector runs (docs/COLLECTORS.md §6): lifecycle, one running run, stale recovery,
cancellation, end statuses, messages and counters, the hook points of the domain layer."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import insert, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from mdt.collectors import registry
from mdt.collectors.base import (
    Candidate,
    Capture,
    Evidence,
    FatalRunError,
    Outcome,
    RunContext,
    RunScope,
)
from mdt.collectors.errors import CollectorUnavailableError, RunInProgressError
from mdt.collectors.replay import ReplayTransport
from mdt.collectors.runs import (
    STALE_ERROR,
    RunEnvironment,
    RunLauncher,
    RunRequest,
    check_runs,
    code_version,
    execute_run,
    recover_stale_runs,
    request_cancel,
    runs_summary,
    start_run,
)
from mdt.collectors.throttle import HostThrottle
from mdt.config import Settings
from mdt.db.models import CollectorRun, FetchLog, RawSnapshot, RunMessage, SourceObservation
from mdt.db.session import create_session_factory, write_transaction
from mdt.domain import observations as observations_domain
from mdt.domain import proposals as proposals_domain
from mdt.domain import reconcile as reconcile_domain
from mdt.domain.errors import InvalidStateError, NotFoundError, ValidationError
from mdt.domain.ids import new_id
from tests.collectors.conftest import FIXTURES, TEST_EMAIL, FakeClock, Site
from tests.collectors.stubs import Behaviour, StubCollector, write_sources
from tests.conftest import Db, make_settings
from tests.helpers import create_project


@dataclass
class Env:
    db: Db
    settings: Settings
    factory: sessionmaker[Session]
    stub: StubCollector
    builtin: StubCollector

    def start(self, collector: str = "stub", **kwargs: Any) -> str:
        transport = kwargs.pop("transport", None)
        kwargs.setdefault("trigger", "cli")
        with self.factory() as session:
            return start_run(
                session, self.settings, RunRequest(collector, **kwargs), transport=transport
            )

    def execute(self, run_id: str, **kwargs: Any) -> str:
        cancel = kwargs.pop("cancel", None)
        kwargs.setdefault("clock", FakeClock())
        kwargs.setdefault("throttle", HostThrottle())
        return execute_run(
            self.factory,
            self.settings,
            run_id,
            cancel=cancel,
            environment=RunEnvironment(**kwargs),
        )

    def run(
        self, behaviour: Behaviour, *, params: Mapping[str, Any] | None = None, **kwargs: Any
    ) -> tuple[str, str]:
        self.stub.behaviour = behaviour
        transport = kwargs.get("transport")
        run_id = self.start(params=dict(params or {}), transport=transport)
        return run_id, self.execute(run_id, **kwargs)

    def row(self, run_id: str) -> CollectorRun:
        with self.factory() as session:
            row = session.get(CollectorRun, run_id)
            assert row is not None
            session.expunge(row)
            return row

    def messages(self, run_id: str) -> list[tuple[str, str, str]]:
        with self.factory() as session:
            rows = session.scalars(
                select(RunMessage).where(RunMessage.run_id == run_id).order_by(RunMessage.id)
            ).all()
            return [(row.level, row.code, row.message) for row in rows]


@pytest.fixture
def env(db: Db, tmp_path: Path, codebook_dir: Path, seed_dir: Path) -> Iterator[Env]:
    settings = make_settings(
        db.root,
        codebook_dir,
        seed_dir,
        sources_file=write_sources(tmp_path),
        contact_email=TEST_EMAIL,
    )
    stub = StubCollector()
    builtin = StubCollector(NAME="stub_builtin", PARAMS=frozenset({"document_ids"}))
    registry.register("stub", stub)
    registry.register("stub_builtin", builtin)
    registry.register("stub_disabled", StubCollector(NAME="stub_disabled"))
    try:
        yield Env(db, settings, create_session_factory(db.engine, settings), stub, builtin)
    finally:
        for name in ("stub", "stub_builtin", "stub_disabled"):
            registry.unregister(name)


def fetch(*urls: str) -> Behaviour:
    def behaviour(ctx: RunContext) -> None:
        for url in urls:
            ctx.client.get(url)
            ctx.count("pages_parsed")

    return behaviour


# --------------------------------------------------------------------------------------
# Lifecycle and end statuses
# --------------------------------------------------------------------------------------


def test_a_run_records_its_requests_snapshots_and_stats(env: Env) -> None:
    site = Site({"https://example.org/a": "<p>a</p>", "https://example.org/b": "<p>b</p>"})
    run_id, status = env.run(
        fetch("https://example.org/a", "https://example.org/b"),
        transport=httpx2.MockTransport(site),
        params={"limit": 5},
    )
    assert status == "succeeded"
    row = env.row(run_id)
    assert (row.collector, row.trigger, row.mode, row.status) == (
        "stub",
        "cli",
        "incremental",
        "succeeded",
    )
    assert row.params == {"limit": 5}
    assert row.finished_at is not None and row.heartbeat_at is not None
    assert row.code_version == code_version() and len(row.config_hash) == 64
    assert row.stats["requests"] == 3 and row.stats["snapshots"] == 2
    assert row.stats["pages_parsed"] == 2 and row.stats["errors"] == 0
    assert row.stats["bytes"] == len("<p>a</p>") * 2
    assert set(row.stats) >= {"items_seen", "proposals_opened", "extra"}
    with env.factory() as session:
        fetches = session.scalars(select(FetchLog).where(FetchLog.run_id == run_id)).all()
        snapshots = session.scalars(select(RawSnapshot).where(RawSnapshot.run_id == run_id)).all()
    assert len(fetches) == 3 and len(snapshots) == 2
    assert {snapshot.source_id for snapshot in snapshots} == {"stub"}


def test_a_failed_request_makes_the_run_partial(env: Env) -> None:
    site = Site({"https://example.org/a": "ok"})
    run_id, status = env.run(
        fetch("https://example.org/a", "https://example.org/missing"),
        transport=httpx2.MockTransport(site),
    )
    assert status == "partial"
    assert ("error", "http_error", "http_error: https://example.org/missing (HTTP 404)") in (
        env.messages(run_id)
    )
    assert env.row(run_id).stats["errors"] == 1


def test_robots_disallowed_urls_do_not_make_the_run_partial(env: Env) -> None:
    site = Site(
        {
            "https://example.org/robots.txt": b"User-agent: *\nDisallow: /private\n",
            "https://example.org/a": "ok",
        }
    )
    run_id, status = env.run(
        fetch("https://example.org/a", "https://example.org/private/x"),
        transport=httpx2.MockTransport(site),
    )
    assert status == "succeeded"
    assert env.row(run_id).stats["robots_disallowed"] == 1


def test_a_fatal_error_fails_the_run(env: Env) -> None:
    def fatal(ctx: RunContext) -> None:
        raise FatalRunError("example.org: blocked")

    run_id, status = env.run(fatal)
    assert status == "failed"
    assert env.row(run_id).error == "example.org: blocked"
    assert ("error", "fatal", "example.org: blocked") in env.messages(run_id)


def test_a_blocked_listing_host_fails_the_run(env: Env) -> None:
    site = Site({"https://example.org/robots.txt": httpx2.Response(403, text="denied")})
    run_id, status = env.run(
        fetch("https://example.org/list"), transport=httpx2.MockTransport(site)
    )
    assert status == "failed"
    assert env.row(run_id).error == "example.org: blocked"
    codes = [code for _, code, _ in env.messages(run_id)]
    assert codes[:1] == ["blocked"] and codes[-1] == "fatal"


def test_an_unexpected_exception_fails_the_run(env: Env) -> None:
    def broken(ctx: RunContext) -> None:
        raise ValueError("synthetic failure")

    run_id, status = env.run(broken)
    assert status == "failed"
    assert env.row(run_id).error == "unexpected error: ValueError: synthetic failure"


def test_a_cancel_request_stops_the_run(env: Env) -> None:
    cancel = threading.Event()
    seen: list[str] = []
    site = Site({"https://example.org/a": "a", "https://example.org/b": "b"})

    def behaviour(ctx: RunContext) -> None:
        ctx.client.get("https://example.org/a")
        ctx.listing_complete()
        cancel.set()
        seen.append("cancelled" if ctx.cancelled() else "running")
        ctx.client.get("https://example.org/b")  # raises: the run stops here
        seen.append("not reached")

    disappearance: list[str] = []
    run_id = env.start()
    env.stub.behaviour = behaviour
    original = observations_domain.disappearance_step
    observations_domain.disappearance_step = lambda session, scope: disappearance.append("x")  # type: ignore[assignment]
    try:
        status = env.execute(run_id, cancel=cancel, transport=httpx2.MockTransport(site))
    finally:
        observations_domain.disappearance_step = original  # type: ignore[assignment]
    assert status == "cancelled" and seen == ["cancelled"]
    assert disappearance == []  # a cancelled run never marks keys as missing
    assert "https://example.org/b" not in site.urls()
    assert env.row(run_id).complete_listing  # recorded, whatever the end status


def test_cancel_requests_of_finished_runs_are_refused(env: Env) -> None:
    run_id, _ = env.run(lambda ctx: None)
    with env.factory() as session:
        with pytest.raises(InvalidStateError) as raised:
            request_cancel(session, run_id)
        assert raised.value.details == {"state": "succeeded"}
        with pytest.raises(NotFoundError):
            request_cancel(session, "run_missing")


def test_a_cancel_from_another_process_reaches_the_run_through_the_heartbeat(env: Env) -> None:
    def wait_for_cancel(ctx: RunContext) -> None:
        with env.factory() as session:
            request_cancel(session, ctx.run_id)  # as `POST /api/runs/{id}/cancel` would
        deadline = time.monotonic() + 5
        while not ctx.cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)

    env.stub.behaviour = wait_for_cancel
    run_id = env.start()
    status = env.execute(run_id, cancel_poll_s=0.02)
    assert status == "cancelled"
    assert env.row(run_id).cancel_requested_at is not None


def test_the_heartbeat_updates_heartbeat_at(env: Env) -> None:
    beats: list[str | None] = []

    def watch(ctx: RunContext) -> None:
        deadline = time.monotonic() + 5
        first = env.row(ctx.run_id).heartbeat_at
        while time.monotonic() < deadline:
            current = env.row(ctx.run_id).heartbeat_at
            if current != first:
                beats.extend([first, current])
                return
            time.sleep(0.02)

    env.stub.behaviour = watch
    run_id = env.start()
    env.execute(run_id, heartbeat_s=0.05, cancel_poll_s=0.02)
    assert len(beats) == 2 and beats[0] is not None and beats[1] is not None
    assert beats[1] > beats[0]


# --------------------------------------------------------------------------------------
# Starting: one running run, stale runs, configuration
# --------------------------------------------------------------------------------------


def test_only_one_run_can_be_running(env: Env) -> None:
    first = env.start()
    with pytest.raises(RunInProgressError) as raised:
        env.start("stub_builtin")
    assert raised.value.details == {"run_id": first}
    assert "(stub) is running" in raised.value.message


def test_stale_runs_are_recovered_before_a_start(env: Env) -> None:
    old = env.start()
    with write_transaction(env.factory()) as session:
        session.execute(
            update(CollectorRun)
            .where(CollectorRun.id == old)
            .values(heartbeat_at="2026-01-01T00:00:00.000000Z")
        )
    new = env.start()
    row = env.row(old)
    assert row.status == "failed" and row.finished_at is not None
    assert row.error == STALE_ERROR.format("2026-01-01T00:00:00.000000Z")
    assert env.row(new).status == "running"


def test_recover_stale_runs_leaves_fresh_runs(env: Env) -> None:
    fresh = env.start()
    with env.factory() as session:
        assert recover_stale_runs(session, env.settings) == []
    assert env.row(fresh).status == "running"


def test_unknown_and_unimplemented_collectors(env: Env) -> None:
    with pytest.raises(NotFoundError):
        env.start("nonexistent")
    with pytest.raises(NotFoundError):
        env.start("stub_unimplemented")


@pytest.mark.parametrize(
    ("contact_email", "replay"),
    [(None, False), ("research-contact@example.org", False), ("not an address", False)],
)
def test_collectors_with_network_need_a_contact_address(
    env: Env, contact_email: str | None, replay: bool
) -> None:
    env.settings = env.settings.model_copy(update={"contact_email": contact_email})
    with pytest.raises(CollectorUnavailableError) as raised:
        env.start()
    assert raised.value.details == {"reason": "contact_email_missing"}
    assert contact_email is None or contact_email not in raised.value.message
    # Built-in collectors and replay runs send nothing over the network.
    builtin = env.start("stub_builtin")
    with env.factory() as session:
        request_cancel(session, builtin)
    env.execute(builtin)
    transport = ReplayTransport([FIXTURES / "ministry_projects"])
    replayed = env.start(transport=transport)
    assert env.row(replayed).params == {"replay": True}


def test_disabled_collectors_cannot_start(env: Env) -> None:
    with pytest.raises(CollectorUnavailableError) as raised:
        env.start("stub_disabled")
    assert raised.value.details == {"reason": "disabled"}


@pytest.mark.parametrize(
    ("mode", "params", "path"),
    [
        ("weekly", {}, "mode"),
        ("incremental", {"speed": 1}, "params.speed"),
        ("incremental", {"recall_sample": 3}, "params.recall_sample"),
        ("incremental", {"limit": 0}, "params.limit"),
        ("incremental", {"limit": True}, "params.limit"),
        ("incremental", {"limit": "5"}, "params.limit"),
        ("incremental", {"refetch": 1}, "params.refetch"),
    ],
)
def test_invalid_modes_and_parameters(
    env: Env, mode: str, params: dict[str, Any], path: str
) -> None:
    with pytest.raises(ValidationError) as raised:
        env.start(mode=mode, params=params)
    assert path in (raised.value.details or {})


def test_document_ids_parameter(env: Env) -> None:
    with pytest.raises(ValidationError):
        env.start("stub_builtin", params={"document_ids": [new_id("prj")]})
    with pytest.raises(ValidationError):
        env.start("stub_builtin", params={"document_ids": []})
    document_id = new_id("doc")
    run_id = env.start("stub_builtin", mode="full", params={"document_ids": [document_id]})
    row = env.row(run_id)
    assert row.mode == "full"
    assert row.params == {"document_ids": [document_id]}


# --------------------------------------------------------------------------------------
# Messages, counters, listing
# --------------------------------------------------------------------------------------


def test_messages_are_capped_per_code_and_counted(env: Env) -> None:
    def chatty(ctx: RunContext) -> None:
        for n in range(205):
            ctx.message("warning", "invalid_value", f"value {n}")
        ctx.message("error", "parse_error", "no loader data", url="https://example.org/p")
        ctx.message("info", "discarded", "not relevant")
        ctx.count("custom_counter", 3)
        ctx.count("pages_parsed")

    run_id, status = env.run(chatty)
    assert status == "partial"  # an error-level message
    stats = env.row(run_id).stats
    assert stats["warnings"] == 205 and stats["messages_suppressed"] == 5
    assert stats["errors"] == 1 and stats["parse_errors"] == 1
    assert stats["extra"] == {"collector_version": 1, "custom_counter": 3}
    assert stats["pages_parsed"] == 1
    codes = [code for _, code, _ in env.messages(run_id)]
    assert codes.count("invalid_value") == 200
    assert codes[-2:] == ["parse_error", "discarded"]


def test_unknown_message_codes_are_programming_errors(env: Env) -> None:
    def wrong(ctx: RunContext) -> None:
        ctx.message("warning", "fatal", "fatal is an error code")

    run_id, status = env.run(wrong)
    assert status == "failed"
    assert "unknown run message warning/fatal" in (env.row(run_id).error or "")


def test_stats_are_written_every_20_requests(env: Env) -> None:
    urls = [f"https://example.org/p{n}" for n in range(25)]
    site = Site(dict.fromkeys(urls, "page"))
    seen: list[int] = []

    def behaviour(ctx: RunContext) -> None:
        for url in urls:
            ctx.client.get(url)
            seen.append(env.row(ctx.run_id).stats["requests"])

    run_id, status = env.run(behaviour, transport=httpx2.MockTransport(site))
    assert status == "succeeded"
    assert seen[18] == 20  # robots.txt + 19 pages: written at the 20th request
    assert seen[17] < 20
    assert env.row(run_id).stats["requests"] == 26


def test_a_run_with_limit_never_sets_a_complete_listing(env: Env) -> None:
    def complete(ctx: RunContext) -> None:
        ctx.listing_complete()

    run_id, _ = env.run(complete, params={"limit": 3})
    assert not env.row(run_id).complete_listing
    run_id, _ = env.run(complete)
    assert env.row(run_id).complete_listing
    assert ("info", "listing_complete") in [(lvl, code) for lvl, code, _ in env.messages(run_id)]


# --------------------------------------------------------------------------------------
# Hook points of the domain layer
# --------------------------------------------------------------------------------------


@pytest.fixture
def domain(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace the domain functions with recorders."""
    calls: dict[str, list[Any]] = {
        "reconcile": [],
        "sighting": [],
        "first_archived": [],
        "disappearance": [],
        "duplicates": [],
    }

    def reconcile(session: Session, scope: RunScope, candidate: Candidate) -> Outcome:
        with write_transaction(session):  # messages inside a write unit are deferred
            scope.message("info", "subject_deleted", f"seen {candidate.key}")
            scope.count("entities_created")
        scope.memory.setdefault("keys", []).append(candidate.key)
        calls["reconcile"].append(candidate.key)
        return Outcome("created", "doc_01JBX3EXAMPLE0000000000000")

    def sighting(session: Session, scope: RunScope, entity_type: str, key: str, **kw: Any) -> None:
        calls["sighting"].append((entity_type, key, kw))

    def first_archived(
        session: Session, scope: RunScope, subject_id: str, capture: Capture, *, exact: bool
    ) -> Outcome:
        calls["first_archived"].append((subject_id, capture.timestamp, exact))
        return Outcome("proposed", None, ("prp_example",))

    monkeypatch.setattr(reconcile_domain, "reconcile_candidate", reconcile)
    monkeypatch.setattr(reconcile_domain, "record_first_archived", first_archived)
    monkeypatch.setattr(observations_domain, "record_sighting", sighting)
    monkeypatch.setattr(
        observations_domain,
        "disappearance_step",
        lambda session, scope: calls["disappearance"].append(scope.run_id),
    )
    monkeypatch.setattr(
        proposals_domain,
        "detect_duplicates",
        lambda session, scope: calls["duplicates"].append(list(scope.memory["keys"])),
    )
    return calls


def candidate(key: str) -> Candidate:
    return Candidate(
        entity_type="document",
        key=key,
        evidence=Evidence(raw_snapshot_id="raw_example", source_url="https://example.org/"),
        fields={"title": "Example document"},
    )


def test_the_framework_calls_the_domain_layer(env: Env, domain: dict[str, list[Any]]) -> None:
    capture = Capture(
        timestamp="20200101000000",
        original="https://example.org/",
        archive_url="https://web.archive.org/web/20200101000000/https://example.org/",
        cdx_row=("org,example)/", "20200101000000", "https://example.org/", "200", "text/html"),
        request_url="https://web.archive.org/cdx/search/cdx?url=example.org",
        raw_snapshot_id="raw_example",
        fetched_at="2026-10-30T10:00:00.000000Z",
    )
    outcomes: list[Outcome] = []

    def behaviour(ctx: RunContext) -> None:
        outcomes.append(ctx.reconcile(candidate("doc:one")))
        outcomes.append(ctx.reconcile(candidate("doc:two")))
        ctx.observe("document", "doc:three", url="https://example.org/3", label="Three")
        outcomes.append(ctx.first_archived("prj_01JBX3EXAMPLE0000000000000", capture, exact=False))
        ctx.listing_complete()

    run_id, status = env.run(behaviour)
    assert status == "succeeded"
    assert domain["reconcile"] == ["doc:one", "doc:two"]
    assert domain["sighting"] == [
        (
            "document",
            "doc:three",
            {"url": "https://example.org/3", "label": "Three", "details": None},
        )
    ]
    assert domain["first_archived"] == [("prj_01JBX3EXAMPLE0000000000000", "20200101000000", False)]
    assert domain["disappearance"] == [run_id]
    assert domain["duplicates"] == [["doc:one", "doc:two"]]
    assert outcomes[0].action == "created" and outcomes[2].proposal_ids == ("prp_example",)
    stats = env.row(run_id).stats
    assert stats["items_seen"] == 3 and stats["entities_created"] == 2
    assert [code for _, code, _ in env.messages(run_id)].count("subject_deleted") == 2


def test_finish_steps_are_skipped_when_they_do_not_apply(
    env: Env, domain: dict[str, list[Any]]
) -> None:
    _, status = env.run(lambda ctx: ctx.observe("document", "doc:seen"))
    assert status == "succeeded"
    assert domain["sighting"] and domain["disappearance"] == [] and domain["duplicates"] == []


def test_candidates_of_undeclared_types_and_bad_keys_are_refused(
    env: Env, domain: dict[str, list[Any]]
) -> None:
    def undeclared(ctx: RunContext) -> None:
        ctx.reconcile(
            Candidate(
                entity_type="project",
                key="entry:x",
                evidence=Evidence(raw_snapshot_id="raw_x", source_url="https://example.org/"),
            )
        )

    run_id, status = env.run(undeclared)
    assert status == "failed" and "declares no type 'project'" in (env.row(run_id).error or "")
    run_id, status = env.run(lambda ctx: ctx.observe("document", "x" * 501))
    assert status == "failed"


# --------------------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------------------


def test_read_helpers(env: Env) -> None:
    with env.factory() as session:
        project = create_project(session, official_urls=["https://example.org/project"])
    found: dict[str, Any] = {}

    def behaviour(ctx: RunContext) -> None:
        with write_transaction(env.factory()) as session:
            session.execute(
                insert(SourceObservation).values(
                    collector="stub",
                    key="entry:example",
                    entity_type="project",
                    subject_id=project.entity_id,
                    first_seen_at="2026-10-30T10:00:00.000000Z",
                    first_seen_run=ctx.run_id,
                    last_seen_at="2026-10-30T10:00:00.000000Z",
                    last_seen_run=ctx.run_id,
                    details={"rubric": "example"},
                )
            )
        found["records"] = ctx.live_records("project", ["official_urls", "name_en"])
        found["observation"] = ctx.observation("entry:example")
        found["missing"] = ctx.observation("entry:other")
        ctx.client.get("https://example.org/robots.txt")
        found["snapshot"] = ctx.latest_snapshot("HTTPS://EXAMPLE.ORG/robots.txt")
        found["none"] = ctx.latest_snapshot("https://example.org/never")

    site = Site({"https://example.org/robots.txt": b"User-agent: *\nAllow: /\n"})
    env.run(behaviour, transport=httpx2.MockTransport(site))
    records = {record["id"]: record for record in found["records"]}
    assert records[project.entity_id] == {
        "id": project.entity_id,
        "official_urls": ["https://example.org/project"],
        "name_en": "Example project",
    }
    assert found["observation"].subject_id == project.entity_id
    assert found["observation"].details == {"rubric": "example"} and found["missing"] is None
    assert found["snapshot"].body == b"User-agent: *\nAllow: /\n" and found["none"] is None


# --------------------------------------------------------------------------------------
# The server's launcher, replay, summaries and checks
# --------------------------------------------------------------------------------------


def test_the_launcher_runs_in_a_thread_and_stops_runs_at_shutdown(env: Env) -> None:
    started = threading.Event()

    def wait(ctx: RunContext) -> None:
        started.set()
        while not ctx.cancelled():
            time.sleep(0.01)

    env.stub.behaviour = wait
    launcher = RunLauncher(env.settings, env.factory)
    with env.factory() as session:
        run_id = launcher.start(session, RunRequest("stub"))
    assert started.wait(5)
    assert env.row(run_id).status == "running"
    launcher.shutdown(timeout=5)
    assert env.row(run_id).status == "cancelled"


def test_the_launcher_cancels_its_own_run_at_once(env: Env) -> None:
    started = threading.Event()

    def wait(ctx: RunContext) -> None:
        started.set()
        while not ctx.cancelled():
            time.sleep(0.01)

    env.stub.behaviour = wait
    launcher = RunLauncher(env.settings, env.factory)
    with env.factory() as session:
        run_id = launcher.start(session, RunRequest("stub"))
        assert started.wait(5)
        launcher.cancel(session, run_id)
    deadline = time.monotonic() + 5
    while env.row(run_id).status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert env.row(run_id).status == "cancelled"


def test_inline_runs_finish_before_start_returns(env: Env) -> None:
    settings = env.settings.model_copy(update={"collector_run_inline": True})
    launcher = RunLauncher(settings, env.factory)
    with env.factory() as session:
        run_id = launcher.start(session, RunRequest("stub_builtin"))
    assert env.row(run_id).status == "succeeded"
    assert env.row(run_id).trigger == "ui"


def test_replay_runs_store_fixture_snapshots(env: Env) -> None:
    transport = ReplayTransport([FIXTURES / "ministry_projects"])
    run_id, status = env.run(fetch("https://thedigital.gov.ua/projects"), transport=transport)
    assert status == "succeeded"
    assert env.row(run_id).params == {"replay": True}
    with env.factory() as session:
        snapshot = session.scalars(select(RawSnapshot).where(RawSnapshot.run_id == run_id)).one()
    assert snapshot.via == "replay"
    assert snapshot.fetched_at == "2026-10-29T12:55:23.195554Z"


def test_runs_summary_and_check(env: Env) -> None:
    with env.factory() as session:
        assert runs_summary(session) == {"running": None, "last_finished": None}
    finished, _ = env.run(lambda ctx: None)
    running = env.start()
    with env.factory() as session:
        summary = runs_summary(session)
        assert summary["running"]["id"] == running  # type: ignore[index]
        assert summary["last_finished"]["id"] == finished  # type: ignore[index]
        assert check_runs(session, env.settings) == []
    with env.db.engine.begin() as connection:
        connection.execute(
            text("UPDATE collector_run SET heartbeat_at = :at WHERE id = :id"),
            {"at": "2026-01-01T00:00:00.000000Z", "id": running},
        )
    with env.factory() as session:
        problems = check_runs(session, env.settings)
    assert problems == [f"run: {running} (stub) has no heartbeat since 2026-01-01 00:00:00 UTC"]


def test_execute_refuses_runs_that_are_not_running(env: Env) -> None:
    run_id, _ = env.run(lambda ctx: None)
    with pytest.raises(InvalidStateError):
        env.execute(run_id)


def test_a_run_that_cannot_start_ends_failed(env: Env, tmp_path: Path) -> None:
    run_id = env.start()
    broken = tmp_path / "broken-replay"
    broken.mkdir()
    (broken / "x.meta.json").write_text("{not json", encoding="utf-8")
    env.settings = env.settings.model_copy(update={"collector_replay_dir": broken})
    status = execute_run(env.factory, env.settings, run_id)
    assert status == "failed"
    row = env.row(run_id)
    assert row.status == "failed" and row.finished_at is not None
    assert (row.error or "").startswith("the run could not start: ReplayIndexError")
    assert [code for _, code, _ in env.messages(run_id)] == ["fatal"]


def test_database_errors_are_reported_without_their_sql(env: Env) -> None:
    def violate(ctx: RunContext) -> None:
        with write_transaction(env.factory()) as session:
            session.execute(text("INSERT INTO fetch_log (run_id, at) VALUES ('x', 'y')"))

    run_id, status = env.run(violate)
    assert status == "failed"
    error = env.row(run_id).error or ""
    assert error.startswith("unexpected error: IntegrityError: NOT NULL constraint failed")
    assert "INSERT INTO" not in error
