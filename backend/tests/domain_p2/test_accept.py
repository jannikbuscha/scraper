"""Accepting and rejecting proposals (docs/DATA_MODEL.md §16.4): accept, edit & accept,
link to existing and reject per kind, with the provenance of §5; evidence of accepted
``create_event`` proposals; bulk decisions with ``stale`` and ``needs_values``. Proposals
are raised by the reconciler from synthetic candidates."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mdt.collectors.base import Capture
from mdt.collectors.duplicates import DuplicatePair
from mdt.db.models import Evidence, Proposal, Revision
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import EntityDeletedError, InvalidStateError, ValidationError
from mdt.domain.observations import disappearance_step
from mdt.domain.proposal_actions import (
    accept_proposal,
    bulk_decide,
    generate_slug,
    reject_proposal,
)
from mdt.domain.proposals import raise_duplicate
from mdt.domain.reconcile import reconcile_candidate, record_first_archived
from mdt.domain.revisions import apply_change, soft_delete
from mdt.domain.run_effects import RunEffects
from mdt.domain.serialize import get_item
from tests.domain_p2.conftest import P2, StubScope, candidate
from tests.helpers import create_project, create_service, fields_of, load

USER = Actor.ui()
URL = "https://example.org/projects/rho"


def rho(p2: P2, **overrides: Any) -> str:
    overrides.setdefault("ministry_urls", [URL])
    with p2.session() as session:
        return create_project(session, name_en="Example rho", **overrides).entity_id


def reconcile(p2: P2, scope: StubScope, **kwargs: Any) -> Any:
    snapshot = kwargs.pop("snapshot", None) or p2.snapshot(scope.run_id, URL)
    key = kwargs.pop("key", "entry:rho")
    url = kwargs.pop("url", URL)
    with p2.session() as session:
        return reconcile_candidate(
            session, scope, candidate("project", key, snapshot, url=url, **kwargs)
        )


def only(p2: P2, *conditions: Any) -> dict[str, Any]:
    [row] = p2.proposals(*conditions)
    return row


def accept(p2: P2, proposal_id: str, **kwargs: Any) -> Any:
    with p2.session() as session:
        return accept_proposal(session, proposal_id, **kwargs)


def latest_revision(p2: P2, entity_id: str) -> Revision:
    with p2.session() as session, read_transaction(session):
        revision = session.scalars(
            select(Revision).where(Revision.entity_id == entity_id).order_by(Revision.id.desc())
        ).first()
        assert revision is not None
        session.expunge(revision)
        return revision


# --------------------------------------------------------------------------------------
# update_field
# --------------------------------------------------------------------------------------


def test_accepting_an_observed_value_keeps_the_collector_as_source(p2: P2) -> None:
    project_id = rho(p2, description_uk="Manual")
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, URL)
    reconcile(p2, scope, snapshot=snapshot, fields={"description_uk": "Source"})
    proposal = only(p2)
    decision = accept(p2, proposal["id"])
    assert (decision.changed, decision.result_id) == (True, project_id)
    with p2.session() as session:
        row = load(session, "project", project_id)
    assert row["description_uk"] == "Source"
    entry = row["field_meta"]["description_uk"]
    assert (entry["src"], entry["by"], entry["locked"]) == (
        f"collector:stub@{scope.run_id}",
        "user",
        True,
    )
    assert entry["raw_snapshot_ids"] == [snapshot] and entry["verified"] == "unverified"
    revision = latest_revision(p2, project_id)
    assert (revision.channel, revision.author, revision.proposal_id) == (
        "ui",
        "user",
        proposal["id"],
    )
    assert revision.note == f"Accepted proposal {proposal['id']}"
    assert decision.revision_ids == [revision.id]
    closed = only(p2)
    assert (closed["state"], closed["decided_by"], closed["result_id"]) == (
        "accepted",
        "user",
        project_id,
    )
    # An accepted value is never proposed again.
    later = p2.scope()
    reconcile(p2, later, fields={"description_uk": "Source"})
    with p2.session() as session:
        apply_change(session, "project", project_id, {"description_uk": "Edited"}, USER)
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    assert len(p2.proposals()) == 1


def test_edit_and_accept_writes_a_manual_value(p2: P2) -> None:
    project_id = rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    proposal = only(p2)
    decision = accept(p2, proposal["id"], values={"description_uk": "Edited"}, note="Why")
    assert decision.changed
    with p2.session() as session:
        row = load(session, "project", project_id)
    assert row["description_uk"] == "Edited"
    assert (
        row["field_meta"]["description_uk"]["src"],
        row["field_meta"]["description_uk"]["raw_snapshot_ids"],
    ) == ("manual", None)
    closed = only(p2)
    assert (closed["state"], closed["decision_note"]) == ("accepted_modified", "Why")
    assert latest_revision(p2, project_id).note == "Why"


def test_edit_values_are_validated_with_value_paths(p2: P2) -> None:
    rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    proposal = only(p2)
    with pytest.raises(ValidationError) as raised:
        accept(p2, proposal["id"], values={"status": "active"})
    assert "values.status" in (raised.value.details or {})


def test_an_add_only_list_appends_to_the_current_list(p2: P2) -> None:
    project_id = rho(p2)
    reconcile(p2, p2.scope(), fields={"ministry_urls": ["https://example.org/x"]})
    proposal = only(p2)
    with p2.session() as session:  # the person adds a URL meanwhile: kept
        apply_change(
            session,
            "project",
            project_id,
            {"ministry_urls": [URL, "https://example.org/meanwhile"]},
            USER,
        )
    accept(p2, proposal["id"])
    with p2.session() as session:
        row = load(session, "project", project_id)
    assert row["ministry_urls"] == [URL, "https://example.org/meanwhile", "https://example.org/x"]
    assert row["field_meta"]["ministry_urls"]["src"] == "manual"


def test_nothing_left_to_write_supersedes_the_proposal(p2: P2) -> None:
    project_id = rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    proposal = only(p2)
    with p2.session() as session:
        apply_change(session, "project", project_id, {"description_uk": "Source"}, USER)
    revisions = p2.revisions()
    decision = accept(p2, proposal["id"])
    assert (decision.changed, decision.revision_ids) == (False, [])
    assert only(p2)["state"] == "superseded" and p2.revisions() == revisions


def test_a_deleted_subject_refuses_and_supersedes(p2: P2) -> None:
    project_id = rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    proposal = only(p2)
    with p2.session() as session:
        soft_delete(session, "project", project_id, USER)
    with pytest.raises(EntityDeletedError):
        accept(p2, proposal["id"])
    assert only(p2)["state"] == "superseded"
    with pytest.raises(InvalidStateError):
        accept(p2, proposal["id"])


def test_rejecting_needs_a_note_and_writes_nothing(p2: P2) -> None:
    project_id = rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    proposal = only(p2)
    revisions = p2.revisions()
    with p2.session() as session:
        with pytest.raises(ValidationError):
            reject_proposal(session, proposal["id"], "  ")
        reject_proposal(session, proposal["id"], "Not right")
    closed = only(p2)
    assert (closed["state"], closed["decision_note"]) == ("rejected", "Not right")
    assert p2.revisions() == revisions
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})  # rejection memory
    assert len(p2.proposals()) == 1
    with p2.session() as session:
        assert fields_of(session, "project", project_id)["description_uk"] == "Manual"


def test_a_text_version_is_accepted_as_a_unit(p2: P2) -> None:
    with p2.session() as session:
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example",
                "url": "https://example.org/d",
                "retrieved_at": "2025-01-01T00:00:00Z",
            },
            USER,
        ).entity_id
    scope = p2.scope()
    snapshot = p2.snapshot(scope.run_id, "https://example.org/d")
    item = candidate(
        "document",
        "doc:d",
        snapshot,
        url="https://example.org/d",
        fields={"title": "Example"},
        text="A new example text.",
        extraction_method="html",
    )
    with p2.session() as session:
        reconcile_candidate(session, scope, item)
    proposal = only(p2, Proposal.field == "text_hash")
    with pytest.raises(ValidationError):
        accept(p2, proposal["id"], values={"text_hash": "x"})
    accept(p2, proposal["id"])
    with p2.session() as session:
        row = load(session, "document", document_id)
    assert (row["text_hash"], row["raw_snapshot_id"], row["extraction_method"]) == (
        proposal["proposed_value"],
        snapshot,
        "html",
    )
    assert row["field_meta"]["text_hash"]["src"] == f"collector:stub@{scope.run_id}"
    assert row["field_meta"]["retrieved_at"]["raw_snapshot_ids"] == [snapshot]


# --------------------------------------------------------------------------------------
# possibly_discontinued and create_entity
# --------------------------------------------------------------------------------------


def discontinued(p2: P2) -> tuple[str, dict[str, Any]]:
    p2.add_term("status", "discontinued")
    p2.add_term("status", "suspended")
    project_id = rho(p2, status="active")
    reconcile(p2, p2.scope())
    for _ in range(2):
        scope = p2.scope()
        with p2.session() as session:
            disappearance_step(session, scope)
    return project_id, only(p2)


def test_accepting_possibly_discontinued_sets_the_status(p2: P2) -> None:
    project_id, proposal = discontinued(p2)
    accept(p2, proposal["id"])
    with p2.session() as session:
        row = load(session, "project", project_id)
    assert row["status"] == "discontinued" and row["field_meta"]["status"]["src"] == "manual"


def test_another_status_is_an_edit(p2: P2) -> None:
    project_id, proposal = discontinued(p2)
    accept(p2, proposal["id"], values={"status": "suspended"})
    assert only(p2)["state"] == "accepted_modified"
    with p2.session() as session:
        assert load(session, "project", project_id)["status"] == "suspended"


def new_entry(p2: P2, **fields: Any) -> dict[str, Any]:
    scope = p2.scope()
    fields.setdefault("name_uk", "Приклад")
    reconcile(
        p2,
        scope,
        key="entry:new_entry",
        url="https://example.org/projects/new_entry",
        fields=fields,
    )
    return only(p2)


def test_a_new_project_needs_its_scope_from_the_person(p2: P2) -> None:
    proposal = new_entry(p2, description_uk="Example")
    with pytest.raises(ValidationError) as raised:
        accept(p2, proposal["id"])
    assert set(raised.value.details or {}) == {"values.in_paper_scope", "values.scope_note"}
    decision = accept(
        p2, proposal["id"], values={"in_paper_scope": False, "scope_note": "Synthetic scope"}
    )
    assert decision.result_id is not None
    with p2.session() as session:
        row = load(session, "project", decision.result_id)
    assert (row["slug"], row["name_uk"], row["description_uk"]) == (
        "new-entry",
        "Приклад",
        "Example",
    )
    meta = row["field_meta"]
    assert meta["name_uk"]["src"].startswith("collector:stub@")
    assert meta["name_uk"]["raw_snapshot_ids"] and meta["name_uk"]["locked"] is True
    assert (meta["scope_note"]["src"], meta["slug"]["src"]) == ("manual", "manual")
    observation = p2.observation("stub", "entry:new_entry")
    assert observation is not None
    assert (observation["subject_id"], observation["bound_by"]) == (decision.result_id, "proposal")
    assert only(p2)["state"] == "accepted"


def test_changing_an_observed_value_is_an_edit(p2: P2) -> None:
    proposal = new_entry(p2)
    decision = accept(
        p2,
        proposal["id"],
        values={"in_paper_scope": True, "scope_note": "Synthetic", "name_uk": "Змінено"},
    )
    assert only(p2)["state"] == "accepted_modified"
    with p2.session() as session:
        assert (
            load(session, "project", decision.result_id)["field_meta"]["name_uk"]["src"] == "manual"
        )


def test_slugs_are_generated_while_taken(p2: P2) -> None:
    with p2.session() as session:
        create_project(session, slug="new-entry")
        assert generate_slug(session, "New_Entry") == "new-entry-2"
        assert generate_slug(session, "--Ä--") == "project"


def test_link_to_existing_binds_and_writes_nothing(p2: P2) -> None:
    proposal = new_entry(p2)
    existing = rho(p2)
    revisions = p2.revisions()
    with pytest.raises(ValidationError):
        accept(p2, proposal["id"], match_id="prj_01JBX3EXAMPLE0000000000000")
    decision = accept(p2, proposal["id"], match_id=existing)
    assert (decision.result_id, decision.revision_ids) == (existing, [])
    assert p2.revisions() == revisions
    assert only(p2)["state"] == "accepted_modified"
    observation = p2.observation("stub", "entry:new_entry")
    assert observation is not None and observation["subject_id"] == existing


# --------------------------------------------------------------------------------------
# create_event and possible_duplicate
# --------------------------------------------------------------------------------------


def test_an_accepted_event_gets_its_evidence_from_the_payload(p2: P2) -> None:
    project_id = rho(p2)
    scope = p2.scope(collector="wayback")
    request = "https://web.archive.org/cdx/search/cdx?url=example.org"
    snapshot = p2.snapshot(scope.run_id, request, source_id="wayback")
    capture = Capture(
        timestamp="20130505120000",
        original="https://example.org/",
        archive_url="https://web.archive.org/web/20130505120000/https://example.org/",
        cdx_row=("org,example)/", "20130505120000", "https://example.org/", "200", "text/html"),
        request_url=request,
        raw_snapshot_id=snapshot,
        fetched_at="2026-02-02T00:00:00.000000Z",
    )
    with p2.session() as session:
        record_first_archived(session, scope, project_id, capture, exact=False)
    proposal = only(p2)
    decision = accept(p2, proposal["id"])
    assert decision.result_id is not None and len(decision.revision_ids) == 2
    with p2.session() as session, read_transaction(session):
        [evidence] = session.scalars(
            select(Evidence).where(Evidence.subject_id == decision.result_id)
        ).all()
        assert (evidence.retrieved_at, evidence.raw_snapshot_id, evidence.archive_url) == (
            "2026-02-02T00:00:00.000000Z",
            snapshot,
            capture.archive_url,
        )
        assert evidence.quote == proposal["quote"]
        batches = set(
            session.scalars(select(Revision.batch_id).where(Revision.id.in_(decision.revision_ids)))
        )
    assert len(batches) == 1 and None not in batches
    with p2.session() as session:
        event = load(session, "event", decision.result_id)
        assert event["field_meta"]["date"]["src"] == "manual"
        assert load(session, "project", project_id)["version"] == 1
        item = get_item(session, "project", project_id)
    assert item["derived"]["existed_by"] == "2013-05-05"


def duplicate_services(p2: P2) -> tuple[str, str, dict[str, Any]]:
    with p2.session() as session:
        project_id = create_project(session, name_en="Example rho").entity_id
        first = create_service(session, project_id, name_en="Example first").entity_id
        second = create_service(session, project_id, name_en="Example second").entity_id
    run_id = p2.new_run()
    with p2.session() as session, write_transaction(session):
        low, high = sorted((first, second))
        raise_duplicate(
            session,
            DuplicatePair(low, high, "name"),
            collector="stub",
            run_id=run_id,
            now=utc_now(),
            effects=RunEffects(),
        )
    return first, second, only(p2)


def test_a_duplicate_of_services_is_accepted_by_merging(p2: P2) -> None:
    first, second, proposal = duplicate_services(p2)
    with pytest.raises(ValidationError):
        accept(p2, proposal["id"])  # the person chooses the survivor
    decision = accept(
        p2, proposal["id"], values={"survivor_id": first, "fields": {"name_en": "merged"}}
    )
    assert decision.result_id == first
    with p2.session() as session:
        survivor = load(session, "service", first)
        merged = load(session, "service", second)
    assert survivor["name_en"] == "Example second"
    assert (merged["merged_into"], merged["deleted_at"] is not None) == (first, True)
    closed = only(p2)
    assert (closed["state"], closed["result_id"]) == ("accepted", first)
    assert latest_revision(p2, second).proposal_id == proposal["id"]


def test_a_duplicate_document_is_screened_out(p2: P2) -> None:
    p2.add_term("exclusion_reason", "duplicate")
    with p2.session() as session:
        documents = [
            apply_change(session, "document", None, {"title": f"Example {n}"}, USER).entity_id
            for n in (1, 2)
        ]
    low, high = sorted(documents)
    run_id = p2.new_run()
    with p2.session() as session, write_transaction(session):
        raise_duplicate(
            session,
            DuplicatePair(low, high, "title_date"),
            collector="stub",
            run_id=run_id,
            now=utc_now(),
            effects=RunEffects(),
        )
    proposal = only(p2)
    decision = accept(p2, proposal["id"], values={"duplicate_id": high})
    assert decision.result_id == high
    with p2.session() as session:
        row = load(session, "document", high)
    assert (row["screening_status"], row["screening_reason"], row["screening_note"]) == (
        "excluded",
        "duplicate",
        f"Duplicate of {low}",
    )


# --------------------------------------------------------------------------------------
# Bulk
# --------------------------------------------------------------------------------------


def test_bulk_accept_leaves_stale_and_value_needing_proposals_open(p2: P2) -> None:
    stale_project = rho(p2, description_uk="Manual")
    reconcile(p2, p2.scope(), fields={"description_uk": "Source"})
    stale = only(p2)
    with p2.session() as session:
        apply_change(session, "project", stale_project, {"description_uk": "Changed"}, USER)
    with p2.session() as session:
        fresh_project = create_project(
            session,
            name_en="Example fresh",
            ministry_urls=["https://example.org/projects/fresh"],
            description_uk="Manual",
        ).entity_id
    reconcile(
        p2,
        p2.scope(),
        key="entry:fresh",
        url="https://example.org/projects/fresh",
        fields={"description_uk": "Source"},
    )
    fresh = only(p2, Proposal.subject_id == fresh_project)
    scope = p2.scope()
    reconcile(
        p2,
        scope,
        key="entry:brand_new",
        url="https://example.org/projects/brand_new",
        fields={"name_uk": "Новий"},
    )
    new = only(p2, Proposal.kind == "create_entity")
    with p2.session() as session:
        result = bulk_decide(
            session,
            [stale["id"], fresh["id"], new["id"], "prp_01JBX3EXAMPLE0000000000000"],
            "accept",
            None,
        )
    statuses = [(item["status"], (item["error"] or {}).get("code")) for item in result.results]
    assert statuses == [
        ("stale", None),
        ("accepted", None),
        ("needs_values", None),
        ("error", "not_found"),
    ]
    with p2.session() as session, read_transaction(session):
        batch = session.scalars(
            select(Revision.batch_id).where(Revision.proposal_id == fresh["id"])
        ).one()
    assert batch == result.batch_id
    with p2.session() as session:
        with pytest.raises(ValidationError):
            bulk_decide(session, [stale["id"]], "reject", None)
        rejected = bulk_decide(session, [stale["id"], new["id"]], "reject", "Not now")
    assert [item["status"] for item in rejected.results] == ["rejected", "rejected"]
