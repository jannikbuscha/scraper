"""Proposal deduplication and superseding (docs/DATA_MODEL.md §16.2, §16.3): refresh of an
open proposal, rejection memory, an accepted key reopened only after a newer value, a new
row after ``superseded``, and the supersede rules. Synthetic values only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import update

from mdt.db.models import Proposal
from mdt.db.session import write_transaction
from mdt.domain.clock import utc_now
from mdt.domain.proposals import (
    ProposalDraft,
    Raised,
    raise_proposal,
    supersede_for_subject,
)
from mdt.domain.run_effects import RunEffects
from tests.domain_p2.conftest import P2
from tests.helpers import create_project


def draft(record: str, value: Any, **overrides: Any) -> ProposalDraft:
    values: dict[str, Any] = {
        "kind": "update_field",
        "entity_type": "project",
        "collector": "stub",
        "target": record,
        "core": ["description_uk", value],
        "subject_id": record,
        "field": "description_uk",
        "current_value": "Current",
        "proposed_value": value,
        "payload": {"field_snapshots": {}},
    }
    values.update(overrides)
    return ProposalDraft(**values)


def raise_(p2: P2, item: ProposalDraft, run_id: str, effects: RunEffects | None = None) -> Raised:
    with p2.session() as session, write_transaction(session):
        return raise_proposal(
            session, item, run_id=run_id, now=utc_now(), effects=effects or RunEffects()
        )


def set_state(p2: P2, proposal_id: str, state: str) -> None:
    with p2.session() as session, write_transaction(session):
        session.execute(
            update(Proposal)
            .where(Proposal.id == proposal_id)
            .values(state=state, decided_at=utc_now(), decided_by="user", decision_note="Test")
        )


def subject(p2: P2) -> str:
    with p2.session() as session:
        return create_project(session).entity_id


def test_an_open_proposal_is_refreshed_once_per_run(p2: P2) -> None:
    record = subject(p2)
    run_one, run_two = p2.new_run(), p2.new_run()
    effects = RunEffects()
    first = raise_(p2, draft(record, "Value"), run_one, effects)
    again = raise_(p2, draft(record, "Value", current_value="Changed"), run_one, effects)
    assert (first.action, again.action, again.proposal_id) == (
        "opened",
        "refreshed",
        first.proposal_id,
    )
    later = RunEffects()
    raise_(p2, draft(record, "Value", payload={"field_snapshots": {"x": ["y"]}}), run_two, later)
    [row] = p2.proposals()
    assert (row["seen_count"], row["first_run_id"], row["last_run_id"]) == (2, run_one, run_two)
    assert row["current_value"] == "Current" and row["payload"] == {"field_snapshots": {"x": ["y"]}}
    assert effects.counts == {"proposals_opened": 1}
    assert later.counts == {"proposals_seen_again": 1}


def test_a_rejected_key_is_never_raised_again(p2: P2) -> None:
    record = subject(p2)
    raised = raise_(p2, draft(record, "Value"), p2.new_run())
    assert raised.proposal_id is not None
    set_state(p2, raised.proposal_id, "rejected")
    assert raise_(p2, draft(record, "Value"), p2.new_run()) == Raised("suppressed")
    assert len(p2.proposals()) == 1


def test_an_accepted_key_reopens_only_after_a_newer_value(p2: P2) -> None:
    record = subject(p2)
    accepted = raise_(p2, draft(record, "A"), p2.new_run())
    assert accepted.proposal_id is not None
    set_state(p2, accepted.proposal_id, "accepted")
    assert raise_(p2, draft(record, "A"), p2.new_run()).action == "suppressed"
    newer = raise_(p2, draft(record, "B"), p2.new_run())  # the source changed ...
    assert newer.action == "opened"
    back = raise_(p2, draft(record, "A"), p2.new_run())  # ... and came back
    assert back.action == "opened"
    states = {row["proposed_value"]: row["state"] for row in p2.proposals()}
    # B was superseded by the newer value A; the old acceptance stays.
    assert [row["state"] for row in p2.proposals()] == ["accepted", "superseded", "open"]
    assert states["B"] == "superseded"


def test_a_superseded_key_opens_a_new_row(p2: P2) -> None:
    record = subject(p2)
    first = raise_(p2, draft(record, "Value"), p2.new_run())
    assert first.proposal_id is not None
    set_state(p2, first.proposal_id, "superseded")
    second = raise_(p2, draft(record, "Value"), p2.new_run())
    assert second.action == "opened" and second.proposal_id != first.proposal_id


def test_a_newer_value_supersedes_the_older_open_one(p2: P2) -> None:
    record = subject(p2)
    raise_(p2, draft(record, "Old"), p2.new_run())
    effects = RunEffects()
    newer = raise_(p2, draft(record, "New"), p2.new_run(), effects)
    old, new = p2.proposals()
    assert (old["state"], old["decided_by"]) == ("superseded", "system")
    assert newer.proposal_id in old["decision_note"]
    assert new["state"] == "open"
    assert effects.counts == {"proposals_opened": 1, "proposals_superseded": 1}


def test_other_collectors_and_fields_are_independent(p2: P2) -> None:
    record = subject(p2)
    raise_(p2, draft(record, "Value"), p2.new_run())
    raise_(p2, draft(record, "Other", collector="other"), p2.new_run("other"))
    raise_(
        p2,
        draft(record, "Other", field="description_en", core=["description_en", "Other"]),
        p2.new_run(),
    )
    assert [row["state"] for row in p2.proposals()] == ["open", "open", "open"]


def test_shared_kinds_deduplicate_across_collectors(p2: P2) -> None:
    record = subject(p2)
    event = {
        "kind": "create_event",
        "entity_type": "event",
        "target": record,
        "core": ["launch", "doc_X", "quote"],
        "subject_id": record,
        "field": None,
        "current_value": None,
        "proposed_value": None,
    }
    first = raise_(p2, draft(record, None, collector="tagger", **event), p2.new_run("tagger"))
    second = raise_(p2, draft(record, None, collector="wayback", **event), p2.new_run("wayback"))
    assert second == Raised("refreshed", first.proposal_id)


def test_superseding_for_a_subject_covers_related_records(p2: P2) -> None:
    record, other = subject(p2), subject(p2)
    raise_(p2, draft(record, "Value"), p2.new_run())
    duplicate = {
        "kind": "possible_duplicate",
        "target": min(record, other),
        "core": max(record, other),
        "subject_id": min(record, other),
        "related_id": max(record, other),
        "field": None,
    }
    raise_(p2, draft(record, None, **duplicate), p2.new_run())
    with p2.session() as session, write_transaction(session):
        closed = supersede_for_subject(session, record, "Example reason", now=utc_now())
    assert len(closed) == 2
    assert {row["decision_note"] for row in p2.proposals()} == {"Example reason"}
