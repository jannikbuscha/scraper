"""Observations and disappearance (docs/DATA_MODEL.md §15.7): keys a complete run did not
see become missing, ``possibly_discontinued`` only after enough complete runs, a key seen
again closes the proposal, documents get none. Synthetic values only."""

from __future__ import annotations

from typing import Any

from mdt.collectors.base import TypeDeclaration
from mdt.db.models import Proposal
from mdt.domain.merge import merge
from mdt.domain.observations import disappearance_step, merged_into_ids, record_sighting
from mdt.domain.reconcile import reconcile_candidate
from tests.domain_p2.conftest import P2, StubScope, candidate, collector_config
from tests.helpers import create_project

URL = "https://example.org/projects/kappa"


def kappa(p2: P2, **overrides: Any) -> str:
    with p2.session() as session:
        return create_project(
            session, name_en="Example kappa", ministry_urls=[URL], **overrides
        ).entity_id


def see(p2: P2, scope: StubScope, key: str = "entry:kappa") -> None:
    with p2.session() as session:
        reconcile_candidate(
            session, scope, candidate("project", key, p2.snapshot(scope.run_id, URL), url=URL)
        )


def finish(p2: P2, scope: StubScope) -> None:
    with p2.session() as session:
        disappearance_step(session, scope)


def complete_run_without(p2: P2, *, after_runs: int = 2) -> StubScope:
    scope = p2.scope(config=collector_config(discontinued_after_runs=after_runs))
    finish(p2, scope)
    return scope


def test_keys_a_complete_run_did_not_see_become_missing(p2: P2) -> None:
    kappa(p2)
    first = p2.scope()
    see(p2, first)
    with p2.session() as session:
        record_sighting(session, first, "document", "news:seen")
    second = p2.scope()
    with p2.session() as session:
        record_sighting(session, second, "document", "news:seen")
    finish(p2, second)
    missing = p2.observation("stub", "entry:kappa")
    seen = p2.observation("stub", "news:seen")
    assert missing is not None and seen is not None
    assert (missing["present"], missing["missing_runs"]) == (False, 1)
    assert (missing["missing_since_run"], missing["missing_since_at"] is not None) == (
        second.run_id,
        True,
    )
    assert (seen["present"], seen["missing_runs"]) == (True, 0)
    assert second.counts["observations_missing"] == 1
    third = p2.scope()
    finish(p2, third)
    again = p2.observation("stub", "entry:kappa")
    assert again is not None and again["missing_runs"] == 2
    assert again["missing_since_run"] == second.run_id  # the first run that missed it


def test_possibly_discontinued_needs_enough_complete_runs(p2: P2) -> None:
    p2.add_term("status", "discontinued")
    project_id = kappa(p2, status="active")
    see(p2, p2.scope())
    complete_run_without(p2)
    assert p2.proposals() == []  # one run is not enough
    second = complete_run_without(p2)
    [proposal] = p2.proposals()
    assert (proposal["kind"], proposal["subject_id"], proposal["state"]) == (
        "possibly_discontinued",
        project_id,
        "open",
    )
    assert proposal["proposed_value"] == {"status": "discontinued"}
    assert proposal["current_value"] == "active"
    assert proposal["payload"]["reason"] == "missing_from_listing"
    assert proposal["payload"]["keys"] == ["entry:kappa"]
    assert proposal["first_run_id"] == second.run_id
    third = complete_run_without(p2)
    [proposal] = p2.proposals()
    assert proposal["seen_count"] == 2 and third.counts["proposals_seen_again"] == 1
    # The key seen again closes it.
    back = p2.scope()
    see(p2, back)
    [proposal] = p2.proposals()
    assert proposal["state"] == "superseded"
    assert proposal["decision_note"] == f"Seen again in run {back.run_id}"


def test_the_threshold_comes_from_the_settings(p2: P2) -> None:
    kappa(p2)
    see(p2, p2.scope())
    complete_run_without(p2, after_runs=1)
    assert [p["kind"] for p in p2.proposals()] == ["possibly_discontinued"]


def test_collectors_without_discontinued_raise_nothing(p2: P2) -> None:
    kappa(p2)
    declaration = {
        "project": TypeDeclaration(creates=False, writes=frozenset(), match_rules=("url_fields",))
    }
    see(p2, p2.scope(declaration=declaration))
    for _ in range(3):
        finish(p2, p2.scope(declaration=declaration))
    assert p2.proposals() == []


def test_a_record_already_discontinued_gets_no_proposal(p2: P2) -> None:
    p2.add_term("status", "discontinued")
    kappa(p2, status="discontinued")
    see(p2, p2.scope())
    complete_run_without(p2)
    complete_run_without(p2)
    assert p2.proposals() == []


def test_all_keys_of_a_subject_must_be_missing(p2: P2) -> None:
    kappa(p2)
    first = p2.scope()
    see(p2, first)
    see(p2, first, key="entry:kappa-second")  # a second key bound to the same record
    for _ in range(2):
        scope = p2.scope()
        see(p2, scope, key="entry:kappa-second")
        finish(p2, scope)
    assert p2.proposals() == []


def test_observations_of_merged_records_count_for_the_survivor(p2: P2) -> None:
    merged_id = kappa(p2)
    with p2.session() as session:
        survivor_id = create_project(session, name_en="Example survivor").entity_id
    see(p2, p2.scope())
    with p2.session() as session:
        merge(session, "project", survivor_id, merged_id, {}, None)
        assert merged_into_ids(session, survivor_id) == [survivor_id, merged_id]
    complete_run_without(p2)
    complete_run_without(p2)
    assert [(p["kind"], p["subject_id"]) for p in p2.proposals(Proposal.state == "open")] == [
        ("possibly_discontinued", survivor_id)
    ]
