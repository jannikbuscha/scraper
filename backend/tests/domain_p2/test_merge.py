"""Merging and unmerging projects and services (docs/DATA_MODEL.md §18): field choices,
repointing of every editable reference and of document links, conflicts, ``merge_log``,
one revision per changed row, unmerge, and the refused plain undelete. Synthetic values."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mdt.db.models import MergeLog, Revision
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import InvalidStateError, MergeConflictError, ValidationError
from mdt.domain.merge import merge, merge_preview, unmerge
from mdt.domain.proposals import ProposalDraft, raise_proposal
from mdt.domain.records import load_links
from mdt.domain.revisions import apply_change, undelete
from mdt.domain.run_effects import RunEffects
from tests.conftest import Db
from tests.domain_p2.conftest import P2
from tests.helpers import create_event, create_project, create_service, focal_org_id, load

USER = Actor.ui()


def create(session: Any, entity_type: str, **data: Any) -> str:
    return apply_change(session, entity_type, None, data, USER).entity_id


def revisions(db: Db, batch_id: str) -> list[Revision]:
    with db.session() as session, read_transaction(session):
        rows = list(
            session.scalars(
                select(Revision).where(Revision.batch_id == batch_id).order_by(Revision.id)
            )
        )
        session.expunge_all()
        return rows


def test_merging_services_repoints_every_reference(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example project").entity_id
        survivor = create_service(
            session,
            project,
            name_en="Example survivor",
            aliases=[{"text": "Survivor"}],
            channels=["channel_a"],
        ).entity_id
        merged = create_service(
            session,
            project,
            name_en="Example merged",
            aliases=[{"text": "Merged"}],
            channels=["channel_b", "channel_a"],
        ).entity_id
        child = create_service(
            session, project, name_en="Example child", parent_service_id=merged
        ).entity_id
        event = create_event(session, merged, "launch", "2014-05").entity_id
        indicator = create(session, "indicator", subject_id=merged, metric="Example", value=1)
        other = create_service(session, project, name_en="Example other").entity_id
        relation = create(
            session, "relation", from_id=merged, to_id=other, relation_type="relates_a"
        )
        participation = create(
            session,
            "participation",
            organization_id=focal_org_id(session),
            subject_id=merged,
            role="operator",
        )
        both = create(
            session,
            "document",
            title="Example both",
            links=[
                {"subject_id": survivor, "state": "suggested"},
                {"subject_id": merged, "state": "confirmed"},
            ],
        )
        evidence = create(
            session,
            "evidence",
            subject_id=merged,
            target="entity",
            url="https://example.org/e",
            retrieved_at="2025-01-01T00:00:00Z",
        )
    p2 = P2(db, db.settings, db.factory)
    run_id = p2.new_run()
    with db.session() as session, write_transaction(session):
        open_proposal = raise_proposal(
            session,
            ProposalDraft(
                kind="update_field",
                entity_type="service",
                collector="stub",
                target=merged,
                core=["notes", "x"],
                subject_id=merged,
                field="notes",
                proposed_value="x",
            ),
            run_id=run_id,
            now=utc_now(),
            effects=RunEffects(),
        ).proposal_id
    with db.session() as session:
        preview = merge_preview(session, "service", survivor, merged)
    assert preview["repoint"] == {
        "service": 1,
        "event": 1,
        "participation": 1,
        "relation": 1,
        "indicator": 1,
        "document": 1,
    }
    assert preview["conflicts"] == []
    assert {field["name"] for field in preview["fields"]} >= {"name_en", "aliases", "channels"}
    with db.session() as session:
        result = merge(
            session,
            "service",
            survivor,
            merged,
            {"name_en": "merged", "aliases": "union", "channels": "union"},
            "Same service",
        )
    with db.session() as session:
        kept = load(session, "service", survivor)
        gone = load(session, "service", merged)
        assert load(session, "service", child)["parent_service_id"] == survivor
        assert load(session, "event", event)["subject_id"] == survivor
        assert load(session, "indicator", indicator)["subject_id"] == survivor
        assert load(session, "relation", relation)["from_id"] == survivor
        assert load(session, "participation", participation)["subject_id"] == survivor
        assert load(session, "evidence", evidence)["subject_id"] == merged  # stays
        with read_transaction(session):
            links = load_links(session, [both])[both]
    assert kept["name_en"] == "Example merged"
    assert [alias["text"] for alias in kept["aliases"]] == ["Survivor", "Merged"]
    assert kept["channels"] == ["channel_a", "channel_b"]
    assert kept["field_meta"]["name_en"]["src"] == "manual"
    assert (gone["merged_into"], gone["deleted_at"] is not None) == (survivor, True)
    assert [(link["subject_id"], link["state"], link["origin"]) for link in links] == [
        (survivor, "confirmed", "manual")
    ]
    rows = revisions(db, result.batch_id)
    assert {row.channel for row in rows} == {"merge"}
    assert sorted(row.entity_id for row in rows) == sorted(
        [survivor, child, event, indicator, relation, participation, both, merged]
    )
    assert {row.action for row in rows if row.entity_id in (survivor, merged)} == {"merge"}
    assert sorted(result.revision_ids) == sorted(row.id for row in rows)
    with db.session() as session, read_transaction(session):
        log = session.get(MergeLog, result.merge_id)
        assert log is not None
        assert log.field_choices == {"name_en": "merged", "aliases": "union", "channels": "union"}
        logged = {(change["entity_type"], change["field"]) for change in log.changes}
    assert ("service", "parent_service_id") in logged and ("document", "links") in logged
    [closed] = p2.proposals()
    assert (closed["id"], closed["state"]) == (open_proposal, "superseded")
    assert closed["decision_note"] == f"Merged into {survivor}"
    with db.session() as session, pytest.raises(InvalidStateError) as raised:
        undelete(session, "service", merged, USER)
    assert raised.value.details == {"state": "merged"}


def test_unmerge_restores_what_was_not_changed_afterwards(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example project").entity_id
        survivor = create_service(session, project, name_en="Example survivor").entity_id
        merged = create_service(session, project, name_en="Example merged").entity_id
        first = create_event(session, merged, "launch", "2014").entity_id
        second = create_event(session, merged, "expansion", "2015").entity_id
        result = merge(session, "service", survivor, merged, {"name_en": "merged"}, None)
        other = create_service(session, project, name_en="Example elsewhere").entity_id
        apply_change(session, "event", second, {"subject_id": other}, USER)  # moved afterwards
        restored = unmerge(session, "service", merged, "Not the same")
    assert restored.merge_id == result.merge_id
    assert restored.skipped == [
        {"entity_type": "event", "id": second, "field": "subject_id", "current": other}
    ]
    with db.session() as session:
        back = load(session, "service", merged)
        assert (back["deleted_at"], back["merged_into"]) == (None, None)
        assert load(session, "event", first)["subject_id"] == merged
        assert load(session, "service", survivor)["name_en"] == "Example survivor"
        with read_transaction(session):
            log = session.get(MergeLog, result.merge_id)
            assert log is not None and log.unmerge_batch_id == restored.batch_id
    assert {row.action for row in revisions(db, restored.batch_id)} == {"unmerge"}
    with db.session() as session, pytest.raises(InvalidStateError):
        unmerge(session, "service", merged, None)


def test_merging_projects_moves_their_service_families(db: Db) -> None:
    with db.session() as session:
        survivor = create_project(session, name_en="Example survivor").entity_id
        merged = create_project(session, name_en="Example merged").entity_id
        parent = create_service(session, merged, name_en="Example parent").entity_id
        child = create_service(
            session, merged, name_en="Example child", parent_service_id=parent
        ).entity_id
        merge(session, "project", survivor, merged, {}, None)
        assert load(session, "service", parent)["project_id"] == survivor
        assert load(session, "service", child)["project_id"] == survivor
        unmerge(session, "project", merged, None)
        assert load(session, "service", child)["project_id"] == merged


@pytest.mark.parametrize("case", ["relation", "other_project", "cycle"])
def test_conflicts_refuse_the_merge(db: Db, case: str) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example project").entity_id
        survivor = create_service(session, project, name_en="Example survivor").entity_id
        merged = create_service(session, project, name_en="Example merged").entity_id
        if case == "relation":
            create(session, "relation", from_id=survivor, to_id=merged, relation_type="relates_a")
        elif case == "other_project":
            elsewhere = create_project(session, name_en="Example elsewhere").entity_id
            survivor = create_service(session, elsewhere, name_en="Example far").entity_id
            create_service(session, project, name_en="Example child", parent_service_id=merged)
        else:
            apply_change(session, "service", survivor, {"parent_service_id": merged}, USER)
    with db.session() as session, read_transaction(session):
        revisions_before = len(list(session.scalars(select(Revision.id))))
    with db.session() as session, pytest.raises(MergeConflictError) as raised:
        merge(session, "service", survivor, merged, {}, None)
    [conflict] = (raised.value.details or {})["conflicts"]
    assert set(conflict) == {"kind", "id", "label", "message"}
    with db.session() as session, read_transaction(session):
        assert len(list(session.scalars(select(Revision.id)))) == revisions_before


def test_invalid_merges_are_refused(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example project").entity_id
        other = create_project(session, name_en="Example other").entity_id
        with pytest.raises(InvalidStateError):
            merge(session, "project", project, project, {}, None)
        with pytest.raises(ValidationError):
            merge(session, "event", project, other, {}, None)
        with pytest.raises(ValidationError) as raised:
            merge(session, "project", project, other, {"slug": "union"}, None)
        assert "fields.slug" in (raised.value.details or {})
        with pytest.raises(ValidationError):
            merge(session, "project", project, other, {"version": "merged"}, None)
