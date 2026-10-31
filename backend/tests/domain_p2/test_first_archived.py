"""``first_archived`` events from Wayback captures (docs/DATA_MODEL.md §15.12): an exact
match creates the event with its evidence, other matches become ``create_event``
proposals, an existing bound makes a capture redundant, a deleted C5 event is not created
again. Every capture is synthetic (example.org, made-up timestamps)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from mdt.collectors.base import Capture, Outcome
from mdt.db.models import Event, Evidence
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.reconcile import record_first_archived
from mdt.domain.revisions import soft_delete
from tests.domain_p2.conftest import P2, StubScope
from tests.helpers import create_event, create_project, load

ORIGINAL = "https://example.org/projects/sigma"


def capture(p2: P2, scope: StubScope, timestamp: str, original: str = ORIGINAL) -> Capture:
    request = f"https://web.archive.org/cdx/search/cdx?url={original}&output=json&limit=1"
    snapshot = p2.snapshot(scope.run_id, request, body=b'[["urlkey"]]', source_id="wayback")
    return Capture(
        timestamp=timestamp,
        original=original,
        archive_url=f"https://web.archive.org/web/{timestamp}/{original}",
        cdx_row=("org,example)/projects/sigma", timestamp, original, "200", "text/html"),
        request_url=request,
        raw_snapshot_id=snapshot,
        fetched_at="2026-01-01T00:00:00.000000Z",
    )


def record(p2: P2, scope: StubScope, subject_id: str, item: Capture, *, exact: bool) -> Outcome:
    with p2.session() as session:
        return record_first_archived(session, scope, subject_id, item, exact=exact)


@pytest.fixture
def sigma(p2: P2) -> str:
    with p2.session() as session:
        return create_project(session, name_en="Example sigma", ministry_urls=[ORIGINAL]).entity_id


def events(p2: P2, subject_id: str) -> list[Event]:
    with p2.session() as session, read_transaction(session):
        rows = list(
            session.scalars(select(Event).where(Event.subject_id == subject_id).order_by(Event.id))
        )
        session.expunge_all()
        return rows


def test_an_exact_match_creates_the_event_and_its_evidence(p2: P2, sigma: str) -> None:
    scope = p2.scope(collector="wayback")
    item = capture(p2, scope, "20131231230000")  # 2014-01-01 in Kyiv
    outcome = record(p2, scope, sigma, item, exact=True)
    assert outcome.action == "created" and outcome.record_id is not None
    [event] = events(p2, sigma)
    assert (event.event_type, event.date_start, event.date_precision, event.date_basis) == (
        "first_archived",
        "2014-01-01",
        "day",
        "archive_upper_bound",
    )
    assert event.date_text == f"20131231230000 {ORIGINAL}"
    assert event.created_by == "collector:wayback"
    with p2.session() as session, read_transaction(session):
        [evidence] = session.scalars(select(Evidence).where(Evidence.subject_id == event.id)).all()
        assert (evidence.target, evidence.url, evidence.archive_url) == (
            "entity",
            item.request_url,
            item.archive_url,
        )
        assert (evidence.raw_snapshot_id, evidence.retrieved_at) == (
            item.raw_snapshot_id,
            item.fetched_at,
        )
        assert json.loads(evidence.quote or "") == list(item.cdx_row)
    with p2.session() as session:
        assert load(session, "project", sigma)["version"] == 1  # the project is not written
    assert scope.counts == {"entities_created": 2, "revisions": 2}


def test_an_existing_earlier_bound_makes_a_capture_redundant(p2: P2, sigma: str) -> None:
    with p2.session() as session:
        create_event(session, sigma, "first_archived", "2012-05-05")
    scope = p2.scope(collector="wayback")
    outcome = record(p2, scope, sigma, capture(p2, scope, "20130101120000"), exact=True)
    assert outcome == Outcome("unchanged", sigma)
    assert len(events(p2, sigma)) == 1


def test_an_earlier_capture_creates_a_second_event(p2: P2, sigma: str) -> None:
    first = p2.scope(collector="wayback")
    record(p2, first, sigma, capture(p2, first, "20150101120000"), exact=True)
    later = p2.scope(collector="wayback")
    outcome = record(p2, later, sigma, capture(p2, later, "20140101120000"), exact=True)
    assert outcome.action == "created"
    assert sorted(event.date_start for event in events(p2, sigma)) == ["2014-01-01", "2015-01-01"]
    # The same captures again write nothing.
    again = p2.scope(collector="wayback")
    revisions = p2.revisions()
    assert record(p2, again, sigma, capture(p2, again, "20140101120000"), exact=True).action == (
        "unchanged"
    )
    assert p2.revisions() == revisions


def test_a_deleted_c5_event_is_not_created_again(p2: P2, sigma: str) -> None:
    first = p2.scope(collector="wayback")
    created = record(p2, first, sigma, capture(p2, first, "20150101120000"), exact=True)
    assert created.record_id is not None
    with p2.session() as session:
        soft_delete(session, "event", created.record_id, Actor.ui())
    later = p2.scope(collector="wayback")
    outcome = record(p2, later, sigma, capture(p2, later, "20150101120000"), exact=True)
    assert outcome == Outcome("unchanged", sigma)


def test_other_matches_become_create_event_proposals(p2: P2, sigma: str) -> None:
    scope = p2.scope(collector="wayback")
    item = capture(p2, scope, "20120101120000", original="https://example.org/")
    outcome = record(p2, scope, sigma, item, exact=False)
    assert outcome.action == "proposed" and events(p2, sigma) == []
    [proposal] = p2.proposals()
    assert (proposal["kind"], proposal["collector"], proposal["subject_id"]) == (
        "create_event",
        "wayback",
        sigma,
    )
    assert proposal["payload"]["event"]["date"] == "2012-01-01"
    assert proposal["payload"]["evidence"]["archive_url"] == item.archive_url
    assert proposal["payload"]["evidence"]["document_id"] is None
    assert json.loads(proposal["quote"]) == list(item.cdx_row)
    # An earlier capture of the same URL refreshes the open proposal.
    later = p2.scope(collector="wayback")
    earlier = capture(p2, later, "20110101120000", original="https://example.org/")
    record(p2, later, sigma, earlier, exact=False)
    [proposal] = p2.proposals()
    assert proposal["payload"]["event"]["date"] == "2011-01-01" and proposal["seen_count"] == 2


def test_a_deleted_subject_blocks_the_capture(p2: P2, sigma: str) -> None:
    with p2.session() as session:
        soft_delete(session, "project", sigma, Actor.ui())
    scope = p2.scope(collector="wayback")
    outcome = record(p2, scope, sigma, capture(p2, scope, "20120101120000"), exact=True)
    assert outcome == Outcome("blocked", sigma)
    assert "subject_deleted" in scope.codes()


def test_a_malformed_timestamp_is_a_collector_bug(p2: P2, sigma: str) -> None:
    scope = p2.scope(collector="wayback")
    with pytest.raises(ValueError, match="14-digit"):
        record(p2, scope, sigma, capture(p2, scope, "2012"), exact=True)
