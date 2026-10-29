"""Optimistic locking and the conflict payload (DATA_MODEL §6.1, §6.5)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from mdt.db.session import read_transaction, write_transaction
from mdt.domain.comments import create_comment, edit_comment
from mdt.domain.errors import ConflictError
from mdt.domain.records import load_row
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.revisions import (
    apply_change,
    restore_version,
    set_field_verification,
    soft_delete,
    undelete,
)
from mdt.domain.writes import WriteUnit, cas_update
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_evidence,
    create_project,
    create_service,
    load,
)


def test_two_interleaved_sessions_one_wins_one_conflicts(db: Db) -> None:
    with db.session() as setup:
        project_id = create_project(setup).entity_id
    with db.session() as first, db.session() as second:
        # Both clients read version 1 ...
        for session in (first, second):
            with read_transaction(session):
                row = load_row(session, ENTITY_TYPES["project"], project_id)
                assert row is not None and row["version"] == 1
        # ... the first write succeeds, the second one conflicts.
        result = apply_change(
            first, "project", project_id, {"name_en": "First"}, ALICE, expected_version=1
        )
        assert result.version == 2
        with pytest.raises(ConflictError) as caught:
            apply_change(
                second, "project", project_id, {"name_en": "Second"}, BOB, expected_version=1
            )
        assert caught.value.payload["current_version"] == 2
    with db.session() as check:
        row = load(check, "project", project_id)
        assert (row["version"], row["name_en"]) == (2, "First")
    assert_matches_latest_snapshot(db, "project", project_id)


def test_concurrent_writers_are_serialised(db: Db) -> None:
    with db.session() as setup:
        project_id = create_project(setup).entity_id
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def write(name: str) -> None:
        with db.session() as session:
            barrier.wait()
            try:
                apply_change(
                    session, "project", project_id, {"name_en": name}, ALICE, expected_version=1
                )
                outcomes.append("ok")
            except ConflictError:
                outcomes.append("conflict")

    threads = [threading.Thread(target=write, args=(name,)) for name in ("One", "Two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    with db.session() as session:
        assert load(session, "project", project_id)["version"] == 2


def test_compare_and_swap_refuses_a_stale_row(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        apply_change(session, "project", project_id, {"name_en": "New"}, BOB, expected_version=1)
        stale = {**load(session, "project", project_id), "version": 1}
        with pytest.raises(ConflictError) as caught, write_transaction(session):
            unit = WriteUnit.open(session, ENTITY_TYPES["project"], ALICE)
            cas_update(unit, stale, {"notes": "lost update"}, action="patch")
        assert caught.value.payload["current_version"] == 2
        assert load(session, "project", project_id)["notes"] is None


def test_conflict_payload(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Base name").entity_id
        apply_change(
            session,
            "project",
            project_id,
            {"name_en": "Their name", "status": "active"},
            BOB,
            note="Their change",
            expected_version=1,
        )
        evidence = create_evidence(session, project_id, "slug", BOB)
        set_field_verification(
            session,
            "project",
            project_id,
            "slug",
            "verified",
            BOB,
            evidence_id=evidence.entity_id,
            expected_version=2,
        )
        with pytest.raises(ConflictError) as caught:
            apply_change(
                session,
                "project",
                project_id,
                {
                    "name_en": "  My name ",
                    "status": "active",
                    "description_en": "My description.",
                },
                ALICE,
                expected_version=1,
            )
        payload = caught.value.payload
        assert caught.value.code == "conflict" and caught.value.status == 409
        assert payload["action"] == "patch"
        assert (payload["entity_type"], payload["entity_id"]) == ("project", project_id)
        assert (payload["base_version"], payload["current_version"]) == (1, 3)
        assert payload["base"]["name_en"] == "Base name"
        assert payload["current"]["name_en"] == "Their name"
        assert payload["changed_since_base"] == ["name_en", "status"]
        assert payload["your_changes"] == {
            "name_en": "My name",
            "status": "active",
            "description_en": "My description.",
        }
        assert payload["conflicting_fields"] == ["name_en"]
        assert payload["meta_changed_since_base"] == {
            "slug": {"verified": ["unverified", "verified"]}
        }
        assert [(r["version"], r["action"], r["author"]) for r in payload["intervening"]] == [
            (2, "update", BOB.by),
            (3, "verify", BOB.by),
        ]
        assert payload["intervening"][0]["note"] == "Their change"
        assert payload["intervening"][0]["changed_fields"] == ["name_en", "status"]
        assert payload["intervening"][1]["changed_fields"] == ["slug"]
        state = {"deleted_at": None, "deleted_by": None, "merged_into": None}
        assert payload["base_state"] == state and payload["current_state"] == state
        assert payload["refs"] == {}
        # Nothing was written.
        assert load(session, "project", project_id)["version"] == 3


def test_conflict_payload_labels_references(db: Db) -> None:
    with db.session() as session:
        first = create_project(session, name_en="First project").entity_id
        second = create_project(session, name_en="Second project").entity_id
        service_id = create_service(session, first).entity_id
        apply_change(session, "service", service_id, {"name_en": "x"}, BOB, expected_version=1)
        with pytest.raises(ConflictError) as caught:
            apply_change(
                session, "service", service_id, {"project_id": second}, ALICE, expected_version=1
            )
        refs = caught.value.payload["refs"]
        assert refs[first] == {
            "id": first,
            "type": "project",
            "label": "First project",
            "deleted": False,
        }
        assert refs[second]["label"] == "Second project"


def test_conflict_without_a_base_revision(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(ConflictError) as caught:
            apply_change(
                session, "project", project_id, {"name_en": "x"}, ALICE, expected_version=7
            )
        payload = caught.value.payload
        assert payload["base"] is None and payload["base_state"] is None
        assert payload["intervening"] == []
        assert "name_en" in payload["changed_since_base"]
        assert payload["conflicting_fields"] == ["name_en"]


def test_every_action_reports_its_conflict_action(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        apply_change(session, "project", project_id, {"status": "active"}, BOB, expected_version=1)
        evidence = create_evidence(session, project_id, "slug")
        actions: dict[str, Callable[[], object]] = {
            "delete": lambda: soft_delete(
                session, "project", project_id, ALICE, expected_version=1
            ),
            "verify": lambda: set_field_verification(
                session,
                "project",
                project_id,
                "slug",
                "verified",
                ALICE,
                evidence_id=evidence.entity_id,
                expected_version=1,
            ),
            "restore": lambda: restore_version(
                session, "project", project_id, 1, ALICE, expected_version=1
            ),
        }
        for action, call in actions.items():
            with pytest.raises(ConflictError) as caught:
                call()
            assert caught.value.payload["action"] == action
        soft_delete(session, "project", project_id, ALICE, expected_version=2)
        with pytest.raises(ConflictError) as caught:
            undelete(session, "project", project_id, ALICE, expected_version=2)
        assert caught.value.payload["action"] == "undelete"
        assert caught.value.payload["current_state"]["deleted_by"] == ALICE.by
        comment = create_comment(session, project_id, "First text", ALICE)
        edit_comment(session, comment.entity_id, "Second text", BOB, expected_version=1)
        with pytest.raises(ConflictError) as caught:
            edit_comment(session, comment.entity_id, "Third text", ALICE, expected_version=1)
        assert caught.value.payload["action"] == "comment"
        assert caught.value.payload["entity_type"] == "comment"
        assert caught.value.payload["conflicting_fields"] == ["body_md"]
