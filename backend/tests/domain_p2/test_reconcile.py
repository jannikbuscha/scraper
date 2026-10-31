"""The reconciler (docs/DATA_MODEL.md §15): matching, new records, the decision table,
record-level verification, add-only URL lists, propose-only fields, unknown codes, the
first candidate per record and run, sightings and write errors. Synthetic values only."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mdt.collectors.base import Outcome
from mdt.db.models import Proposal, Revision, SourceObservation
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.merge import merge
from mdt.domain.observations import record_sighting
from mdt.domain.reconcile import archive_key, reconcile_candidate, urls_to_add
from mdt.domain.revisions import apply_change, soft_delete
from tests.domain_p2.conftest import P2, StubScope, candidate
from tests.helpers import create_project, create_service, fields_of, load

USER = Actor.ui()
ALPHA_URL = "https://example.org/projects/alpha"


def run(p2: P2, scope: StubScope, *candidates: Any) -> list[Outcome]:
    with p2.session() as session:
        return [reconcile_candidate(session, scope, item) for item in candidates]


def project_candidate(p2: P2, scope: StubScope, key: str = "entry:alpha", **kwargs: Any) -> Any:
    snapshot = kwargs.pop("snapshot", None) or p2.snapshot(scope.run_id, ALPHA_URL)
    kwargs.setdefault("url", ALPHA_URL)
    return candidate("project", key, snapshot, **kwargs)


def alpha(p2: P2, actor: Actor = USER, **overrides: Any) -> str:
    overrides.setdefault("ministry_urls", [ALPHA_URL])
    with p2.session() as session:
        return create_project(session, actor, name_en="Example alpha", **overrides).entity_id


def meta(p2: P2, entity_type: str, entity_id: str, name: str) -> dict[str, Any]:
    with p2.session() as session:
        entry = load(session, entity_type, entity_id)["field_meta"][name]
    assert isinstance(entry, dict)
    return entry


# --------------------------------------------------------------------------------------
# Matching and updates
# --------------------------------------------------------------------------------------


def test_a_url_match_binds_the_key_and_unlocked_fields_are_written(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, ALPHA_URL)
    item = project_candidate(
        p2, scope, snapshot=snapshot, url=ALPHA_URL + "/", fields={"description_uk": "Example"}
    )
    [outcome] = run(p2, scope, item)
    assert outcome == Outcome("updated", project_id, ())
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "Example"
    assert meta(p2, "project", project_id, "description_uk") == {
        "src": f"collector:stub@{scope.run_id}",
        "by": "collector:stub",
        "at": meta(p2, "project", project_id, "description_uk")["at"],
        "locked": False,
        "verified": "unverified",
        "evidence_id": None,
        "restored_from_version": None,
        "raw_snapshot_ids": [snapshot],
    }
    observation = p2.observation("stub", "entry:alpha")
    assert observation is not None
    assert (observation["subject_id"], observation["bound_by"]) == (project_id, "auto")
    with p2.session() as session, read_transaction(session):
        revision = session.scalars(
            select(Revision).where(Revision.entity_id == project_id).order_by(Revision.id.desc())
        ).first()
        assert revision is not None
        assert (revision.channel, revision.author, revision.run_id) == (
            "collector",
            "collector:stub",
            scope.run_id,
        )
    assert scope.counts == {"observations_new": 1, "entities_updated": 1, "revisions": 1}


def test_a_second_run_with_the_same_values_writes_nothing(p2: P2) -> None:
    project_id = alpha(p2)
    first = p2.scope()
    run(p2, first, project_candidate(p2, first, fields={"description_uk": "Example"}))
    revisions = p2.revisions()
    second = p2.scope()
    [outcome] = run(p2, second, project_candidate(p2, second, fields={"description_uk": "Example"}))
    assert outcome == Outcome("unchanged", project_id, ())
    assert p2.revisions() == revisions and p2.proposals() == []
    observation = p2.observation("stub", "entry:alpha")
    assert observation is not None and observation["last_seen_run"] == second.run_id
    assert dict(second.counts) == {}


def test_empty_values_never_clear_a_field(p2: P2) -> None:
    project_id = alpha(p2, description_uk="Kept")
    scope = p2.scope()
    [outcome] = run(
        p2, scope, project_candidate(p2, scope, fields={"description_uk": "", "official_urls": []})
    )
    assert outcome.action == "unchanged"
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "Kept"


def test_a_locked_field_becomes_a_proposal_and_keeps_the_manual_value(p2: P2) -> None:
    project_id = alpha(p2, description_uk="Manual value")
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, ALPHA_URL)
    [outcome] = run(
        p2,
        scope,
        project_candidate(p2, scope, snapshot=snapshot, fields={"description_uk": "Source"}),
    )
    assert outcome.action == "proposed" and len(outcome.proposal_ids) == 1
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "Manual value"
    [proposal] = p2.proposals()
    assert (proposal["kind"], proposal["state"], proposal["subject_id"]) == (
        "update_field",
        "open",
        project_id,
    )
    assert (proposal["field"], proposal["current_value"], proposal["proposed_value"]) == (
        "description_uk",
        "Manual value",
        "Source",
    )
    assert proposal["payload"] == {"field_snapshots": {"description_uk": [snapshot]}}
    assert (proposal["raw_snapshot_id"], proposal["first_run_id"]) == (snapshot, scope.run_id)
    assert scope.counts["proposals_opened"] == 1


def test_the_source_agreeing_again_supersedes_the_open_proposal(p2: P2) -> None:
    alpha(p2, description_uk="Manual value")
    first = p2.scope()
    run(p2, first, project_candidate(p2, first, fields={"description_uk": "Source"}))
    second = p2.scope()
    run(p2, second, project_candidate(p2, second, fields={"description_uk": "Manual value"}))
    [proposal] = p2.proposals()
    assert (proposal["state"], proposal["decided_by"]) == ("superseded", "system")
    assert "agrees" in proposal["decision_note"]
    assert second.counts["proposals_superseded"] == 1


def test_a_verified_record_turns_every_difference_into_a_proposal(p2: P2) -> None:
    with p2.session() as session:
        project_id = create_project(
            session, name_en="Example alpha", ministry_urls=[ALPHA_URL]
        ).entity_id
        service_id = create_service(
            session, project_id, urls=["https://example.org/svc/a"]
        ).entity_id
        apply_change(
            session,
            "service",
            service_id,
            {"verification_status": "verified"},
            USER,
            note="Checked",
        )
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, "https://example.org/svc/a")
    item = candidate(
        "service",
        "service:a",
        snapshot,
        url="https://example.org/svc/a",
        fields={
            "description_uk": "Example",  # unlocked, but the record is verified
            "source_categories": [
                {"source": "stub", "label": "Example", "url": "https://example.org/c"}
            ],  # a system field
        },
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "proposed"
    assert sorted(p["field"] for p in p2.proposals()) == ["description_uk", "source_categories"]
    with p2.session() as session:
        values = fields_of(session, "service", service_id)
    assert values["description_uk"] is None and values["source_categories"] is None


def test_system_fields_are_written_although_their_entry_is_locked(p2: P2) -> None:
    with p2.session() as session:
        project_id = create_project(session, name_en="Example alpha").entity_id
        service_id = create_service(
            session, project_id, urls=["https://example.org/svc/a"]
        ).entity_id
    categories = [{"source": "stub", "label": "Example", "url": "https://example.org/c"}]
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, "https://example.org/svc/a")
    item = candidate(
        "service",
        "service:a",
        snapshot,
        url="https://example.org/svc/a",
        fields={"source_categories": categories},
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "updated"
    with p2.session() as session:
        assert fields_of(session, "service", service_id)["source_categories"] == categories


# --------------------------------------------------------------------------------------
# Add-only URL lists, propose-only fields, create-only fields, unknown codes
# --------------------------------------------------------------------------------------


def test_url_lists_are_add_only(p2: P2) -> None:
    assert urls_to_add(
        ["https://example.org/a"], ["https://EXAMPLE.org/a/", "https://example.org/b"]
    ) == ["https://example.org/b"]
    project_id = alpha(p2)  # ministry_urls written by the user: locked
    scope = p2.scope()
    item = project_candidate(
        p2, scope, fields={"ministry_urls": ["https://example.org/x", ALPHA_URL]}
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "proposed"
    [proposal] = p2.proposals()
    assert proposal["proposed_value"] == ["https://example.org/x"]
    assert proposal["current_value"] == [ALPHA_URL]
    # Unlocked: the new URLs are appended, nothing is removed or reordered.
    with p2.session() as session:
        service_project = create_project(session, name_en="Example beta").entity_id
        service_id = create_service(
            session,
            service_project,
            Actor.collector("other", scope.run_id),
            urls=["https://example.org/svc/b", "https://example.org/svc/c"],
        ).entity_id
    later = p2.scope()
    snapshot = p2.snapshot(later.run_id, "https://example.org/svc/b")
    item = candidate(
        "service",
        "service:b",
        snapshot,
        url="https://example.org/svc/b",
        fields={"urls": ["https://example.org/svc/d", "https://example.org/svc/b"]},
    )
    [outcome] = run(p2, later, item)
    assert outcome.action == "updated"
    with p2.session() as session:
        assert fields_of(session, "service", service_id)["urls"] == [
            "https://example.org/svc/b",
            "https://example.org/svc/c",
            "https://example.org/svc/d",
        ]
    assert project_id


def test_propose_only_fields_are_always_proposed(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    [outcome] = run(
        p2,
        scope,
        project_candidate(p2, scope, proposed={"official_urls": ["https://example.org/home"]}),
    )
    assert outcome.action == "proposed"
    [proposal] = p2.proposals()
    assert (proposal["field"], proposal["proposed_value"]) == (
        "official_urls",
        ["https://example.org/home"],
    )
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["official_urls"] == []


def test_create_only_fields_never_change_a_bound_record(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    [outcome] = run(p2, scope, project_candidate(p2, scope, fields={"name_uk": "Інша назва"}))
    assert outcome.action == "unchanged" and p2.proposals() == []
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["name_uk"] is None


def test_unknown_codes_are_dropped_with_a_warning(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    item = project_candidate(
        p2,
        scope,
        fields={"ministry_categories": ["category_a", "example_missing"]},
        details={"code_labels": {"example_missing": "Example label"}},
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "updated"
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["ministry_categories"] == ["category_a"]
    [warning] = [m for m in scope.messages if m[1] == "unknown_code"]
    assert warning[0] == "warning" and "example_missing" in warning[2]
    assert warning[3]["label"] == "Example label" and warning[3]["subject_id"] == project_id


def test_invalid_values_are_dropped_with_a_warning(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    item = project_candidate(
        p2, scope, fields={"ministry_urls": ["not a url"], "description_uk": "Example"}
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "updated"
    assert "invalid_value" in scope.codes()
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "Example"


def test_undeclared_fields_are_a_collector_bug(p2: P2) -> None:
    scope = p2.scope()
    with pytest.raises(ValueError, match="outside the declaration"):
        run(p2, scope, project_candidate(p2, scope, fields={"status": "active"}))


# --------------------------------------------------------------------------------------
# Matching rules, deleted and merged records
# --------------------------------------------------------------------------------------


def test_an_unmatched_entry_becomes_a_create_entity_proposal(p2: P2) -> None:
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, "https://example.org/projects/new_one")
    item = candidate(
        "project",
        "entry:new_one",
        snapshot,
        url="https://example.org/projects/new_one",
        fields={"name_uk": "Приклад", "description_uk": "Example"},
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "proposed" and outcome.record_id is None
    [proposal] = p2.proposals()
    assert proposal["kind"] == "create_entity" and proposal["subject_id"] is None
    assert proposal["payload"] == {
        "fields": {"name_uk": "Приклад", "description_uk": "Example"},
        "field_snapshots": {"name_uk": [snapshot], "description_uk": [snapshot]},
        "candidates": [],
        "observation_key": "entry:new_one",
        "site_slug": "new_one",
    }
    observation = p2.observation("stub", "entry:new_one")
    assert observation is not None and observation["subject_id"] is None
    assert proposal["observation_id"] == observation["id"]
    # The next run refreshes the open proposal instead of opening a second one.
    later = p2.scope()
    run(
        p2,
        later,
        candidate(
            "project",
            "entry:new_one",
            p2.snapshot(later.run_id),
            url=item.url,
            fields={"name_uk": "Приклад 2"},
        ),
    )
    [proposal] = p2.proposals()
    assert proposal["seen_count"] == 2 and proposal["payload"]["fields"] == {"name_uk": "Приклад 2"}
    assert later.counts["proposals_seen_again"] == 1


def test_several_live_matches_bind_nothing(p2: P2) -> None:
    first = alpha(p2)
    second = alpha(p2)
    scope = p2.scope()
    [outcome] = run(p2, scope, project_candidate(p2, scope, fields={"description_uk": "Example"}))
    assert outcome.action == "proposed"
    [proposal] = p2.proposals()
    assert proposal["payload"]["candidates"] == sorted([first, second])
    observation = p2.observation("stub", "entry:alpha")
    assert observation is not None and observation["subject_id"] is None


def test_a_deleted_match_blocks_the_candidate(p2: P2) -> None:
    project_id = alpha(p2)
    with p2.session() as session:
        soft_delete(session, "project", project_id, USER)
    scope = p2.scope()
    [outcome] = run(p2, scope, project_candidate(p2, scope, fields={"description_uk": "Example"}))
    assert outcome == Outcome("blocked", project_id)
    assert p2.proposals() == [] and "subject_deleted" in scope.codes()
    observation = p2.observation("stub", "entry:alpha")
    assert observation is not None and observation["subject_id"] is None


def test_a_bound_key_of_a_deleted_record_writes_nothing(p2: P2) -> None:
    project_id = alpha(p2, description_uk="Manual")
    first = p2.scope()
    run(p2, first, project_candidate(p2, first, fields={"description_uk": "Source"}))
    with p2.session() as session:
        soft_delete(session, "project", project_id, USER)
    later = p2.scope()
    [outcome] = run(p2, later, project_candidate(p2, later, fields={"description_uk": "Again"}))
    assert outcome == Outcome("blocked", project_id)
    [proposal] = p2.proposals()  # the open proposal of the deleted subject is superseded
    assert (
        proposal["state"] == "superseded" and proposal["decision_note"] == "The subject was deleted"
    )


def test_the_external_id_rule_finds_the_record_of_a_renamed_key(p2: P2) -> None:
    project_id = alpha(p2)
    first = p2.scope()
    run(p2, first, project_candidate(p2, first, external_id="example-uuid"))
    later = p2.scope()
    item = project_candidate(
        p2,
        later,
        key="entry:alpha-renamed",
        url="https://example.org/projects/elsewhere",
        external_id="example-uuid",
        fields={"description_uk": "Example"},
    )
    [outcome] = run(p2, later, item)
    assert outcome == Outcome("updated", project_id, ())
    observation = p2.observation("stub", "entry:alpha-renamed")
    assert observation is not None and observation["subject_id"] == project_id


def test_a_merged_subject_is_followed_to_its_survivor(p2: P2) -> None:
    merged_id = alpha(p2)
    with p2.session() as session:
        survivor_id = create_project(session, name_en="Example survivor").entity_id
    first = p2.scope()
    run(p2, first, project_candidate(p2, first))
    with p2.session() as session:
        merge(session, "project", survivor_id, merged_id, {}, None)
    later = p2.scope()
    [outcome] = run(p2, later, project_candidate(p2, later, fields={"description_uk": "Example"}))
    assert outcome == Outcome("updated", survivor_id, ())
    observation = p2.observation("stub", "entry:alpha")
    assert observation is not None and observation["subject_id"] == merged_id  # kept


def test_one_candidate_per_record_and_run(p2: P2) -> None:
    project_id = alpha(p2)
    scope = p2.scope()
    first = project_candidate(p2, scope, fields={"description_uk": "First"})
    second = project_candidate(
        p2, scope, key="entry:alpha-again", fields={"description_uk": "Second"}
    )
    outcomes = run(p2, scope, first, second)
    assert [o.action for o in outcomes] == ["updated", "observed"]
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "First"
    [conflict] = [m for m in scope.messages if m[1] == "conflicting_candidates"]
    assert conflict[3]["keys"] == ["entry:alpha", "entry:alpha-again"]
    observation = p2.observation("stub", "entry:alpha-again")
    assert observation is not None and observation["subject_id"] == project_id


# --------------------------------------------------------------------------------------
# Direct creates
# --------------------------------------------------------------------------------------


def test_a_direct_create_binds_the_key_with_collector_provenance(p2: P2) -> None:
    with p2.session() as session:
        project_id = create_project(session, name_en="Example alpha").entity_id
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, "https://example.org/svc/new")
    item = candidate(
        "service",
        "service:new",
        snapshot,
        url="https://example.org/svc/new",
        external_id="new",
        fields={
            "project_id": project_id,
            "name_uk": "Приклад послуги",
            "urls": ["https://example.org/svc/new"],
            "channels": ["channel_b", "channel_a"],
        },
    )
    [outcome] = run(p2, scope, item)
    assert outcome.action == "created" and outcome.record_id is not None
    with p2.session() as session:
        service = load(session, "service", outcome.record_id)
    assert (service["created_by"], service["verification_status"]) == (
        "collector:stub",
        "unverified",
    )
    assert service["field_meta"]["name_uk"]["raw_snapshot_ids"] == [snapshot]
    assert service["field_meta"]["name_uk"]["locked"] is False
    observation = p2.observation("stub", "service:new")
    assert observation is not None and observation["subject_id"] == outcome.record_id
    assert scope.counts["entities_created"] == 1
    assert scope.memory["mdt.duplicate_candidates"]["service"] == {outcome.record_id}


def test_an_incomplete_candidate_creates_nothing(p2: P2) -> None:
    scope = p2.scope()
    item = candidate("service", "service:nameless", p2.snapshot(scope.run_id), fields={})
    [outcome] = run(p2, scope, item)
    assert outcome == Outcome("observed")
    assert "incomplete_candidate" in scope.codes()
    assert p2.observation("stub", "service:nameless") is not None


def test_a_write_error_keeps_the_key_observed(p2: P2) -> None:
    scope = p2.scope()
    item = candidate(
        "document",
        "doc:bad",
        p2.snapshot(scope.run_id, "https://example.org/doc/bad"),
        url="https://example.org/doc/bad",
        fields={"title": "Example", "url": "https://example.org/doc/bad", "published": "2014"},
    )
    [outcome] = run(p2, scope, item)  # published without published_basis
    assert outcome == Outcome("observed")
    assert [m[0] for m in scope.messages if m[1] == "write_error"] == ["error"]
    assert p2.observation("stub", "doc:bad") is not None
    assert scope.counts["entities_created"] == 0


# --------------------------------------------------------------------------------------
# Sightings and the archive key
# --------------------------------------------------------------------------------------


def test_sightings_upsert_their_observation(p2: P2) -> None:
    first = p2.scope()
    with p2.session() as session:
        record_sighting(
            session,
            first,
            "document",
            "news:one",
            url="https://example.org/n1",
            label="One",
            details={"listing": "a"},
        )
    later = p2.scope()
    with p2.session() as session:
        record_sighting(session, later, "document", "news:one", details={"extra": "b"})
    observation = p2.observation("stub", "news:one")
    assert observation is not None
    assert (observation["first_seen_run"], observation["last_seen_run"]) == (
        first.run_id,
        later.run_id,
    )
    assert observation["details"] == {"listing": "a", "extra": "b"}
    assert (observation["url"], observation["label"], observation["subject_id"]) == (
        "https://example.org/n1",
        "One",
        None,
    )
    assert first.counts == {"observations_new": 1} and dict(later.counts) == {}


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://www.Example.org/Projects/Alpha/?q=1#top", "example.org/projects/alpha"),
        ("http://example.org:8080/a", "example.org:8080/a"),
        ("https://example.org:443/", "example.org"),
        ("example.org./projects/", "example.org/projects"),
    ],
)
def test_archive_keys(url: str, key: str) -> None:
    assert archive_key(url) == key


def test_proposals_count_rows_of_their_run(p2: P2) -> None:
    alpha(p2, description_uk="Manual")
    scope = p2.scope()
    run(p2, scope, project_candidate(p2, scope, fields={"description_uk": "Source"}))
    assert p2.count(Proposal, Proposal.first_run_id == scope.run_id) == 1
    assert p2.count(SourceObservation, SourceObservation.first_seen_run == scope.run_id) == 1


def test_a_create_entity_proposal_lapses_when_its_key_matches_a_record(p2: P2) -> None:
    url = "https://example.org/projects/later"
    scope = p2.scope()
    run(p2, scope, candidate("project", "entry:later", p2.snapshot(scope.run_id), url=url))
    with p2.session() as session:  # the person adds the URL to an existing project
        project_id = create_project(session, name_en="Example later", ministry_urls=[url]).entity_id
    later = p2.scope()
    [outcome] = run(
        p2, later, candidate("project", "entry:later", p2.snapshot(later.run_id), url=url)
    )
    assert outcome.record_id == project_id
    [proposal] = p2.proposals()
    assert proposal["state"] == "superseded"
    assert proposal["decision_note"] == f"The source entry now matches {project_id}"
