"""Bulk edit (DATA_MODEL §6.4, docs/API.md §3.2)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.revisions import apply_change, bulk_apply, soft_delete
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_project,
    fields_of,
    revisions_of,
)

MISSING = "prj_01JBX3ABCDEFGHJKMNPQRSTVWX"


def test_results_per_item(db: Db) -> None:
    with db.session() as session:
        updated = create_project(session).entity_id
        unchanged = create_project(session, status="active").entity_id
        conflicted = create_project(session, policy_domains=["domain_c"]).entity_id
        apply_change(session, "project", conflicted, {"name_en": "x"}, BOB, expected_version=1)
        deleted = create_project(session).entity_id
        soft_delete(session, "project", deleted, ALICE, expected_version=1)
        result = bulk_apply(
            session,
            "project",
            [
                {"id": updated, "expected_version": 1},
                {"id": unchanged, "expected_version": 1},
                {"id": conflicted, "expected_version": 1},
                {"id": deleted, "expected_version": 2},
                {"id": MISSING, "expected_version": 1},
            ],
            ALICE,
            set_values={"status": "active"},
            add={"policy_domains": ["domain_a"]},
            note="Bulk example",
        )
        by_id = {item.id: item.as_dict() for item in result.results}
        assert by_id[updated] == {
            "id": updated,
            "status": "updated",
            "version": 2,
            "current_version": None,
            "current_values": None,
            "error": None,
        }
        # Nothing differs for "unchanged" except the added domain.
        assert by_id[unchanged]["status"] == "updated"
        assert by_id[conflicted]["status"] == "conflict"
        assert by_id[conflicted]["current_version"] == 2
        assert by_id[conflicted]["current_values"] == {
            "status": None,
            "policy_domains": ["domain_c"],
        }
        assert by_id[deleted]["status"] == "entity_deleted"
        assert by_id[MISSING]["status"] == "error"
        assert by_id[MISSING]["error"]["code"] == "not_found"
        for entity_id in (updated, unchanged):
            revision = revisions_of(session, entity_id)[-1]
            assert (revision.batch_id, revision.note) == (result.batch_id, "Bulk example")
        again = bulk_apply(
            session,
            "project",
            [{"id": updated, "expected_version": 2}],
            ALICE,
            set_values={"status": "active"},
        )
        assert again.results[0].status == "unchanged"
        assert again.results[0].version == 2
    assert_matches_latest_snapshot(db, "project", updated)


def test_add_and_remove_keep_order(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(
            session, policy_domains=["domain_b"], beneficiaries=["group_a", "group_b"]
        ).entity_id
        bulk_apply(
            session,
            "project",
            [{"id": project_id, "expected_version": 1}],
            ALICE,
            add={"policy_domains": ["domain_c", "domain_b", "domain_a"]},
            remove={"beneficiaries": ["group_a", "group_x"]},
        )
        fields = fields_of(session, "project", project_id)
        assert fields["policy_domains"] == ["domain_b", "domain_c", "domain_a"]
        assert fields["beneficiaries"] == ["group_b"]


def test_item_errors_do_not_affect_other_items(db: Db) -> None:
    with db.session() as session:
        good = create_project(session).entity_id
        bad = create_project(session).entity_id
        result = bulk_apply(
            session,
            "project",
            [{"id": good, "expected_version": 1}, {"id": bad, "expected_version": 1}],
            ALICE,
            set_values={"in_paper_scope": True, "scope_note": "Synthetic reason."},
        )
        assert [item.status for item in result.results] == ["updated", "updated"]
        for entity_id in (good, bad):
            assert fields_of(session, "project", entity_id)["scope_note"] == "Synthetic reason."
        # An inactive code fails per item with the error object.
        failing = bulk_apply(
            session,
            "project",
            [{"id": good, "expected_version": 2}],
            ALICE,
            set_values={"status": "retired"},
        )
        assert failing.results[0].status == "error"
        assert failing.results[0].error is not None
        assert failing.results[0].error["code"] == "validation_error"


@pytest.mark.parametrize(
    ("kwargs", "path"),
    [
        ({"set_values": {"name_en": "x"}}, "set.name_en"),
        ({"set_values": {"notes": "x"}}, "set.notes"),
        ({"add": {"status": ["active"]}}, "add.status"),
        (
            {"set_values": {"policy_domains": ["domain_a"]}, "remove": {"policy_domains": []}},
            "policy_domains",
        ),
        ({"set_values": {"in_paper_scope": True}}, "set.scope_note"),
        ({"set_values": {"verification_status": "verified"}}, "note"),
        ({"set_values": {"launch": "2020"}}, "set.launch"),
        ({"set_values": {"unicorn": True}}, "set.unicorn"),
        ({}, "set"),
    ],
)
def test_invalid_requests_are_refused_as_a_whole(db: Db, kwargs: dict[str, Any], path: str) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(ValidationError) as caught:
            bulk_apply(
                session, "project", [{"id": project_id, "expected_version": 1}], ALICE, **kwargs
            )
        assert path in (caught.value.details or {})
        assert len(revisions_of(session, project_id)) == 1


def test_invalid_item_lists(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        item = {"id": project_id, "expected_version": 1}
        for items, path in (
            ([], "items"),
            ([item, item], "items[1].id"),
            ([{"id": project_id}], "items[0].expected_version"),
            ([{"expected_version": 1}], "items[0].id"),
            ([item] * 501, "items"),
        ):
            with pytest.raises(ValidationError) as caught:
                bulk_apply(session, "project", items, ALICE, set_values={"status": "active"})
            assert path in (caught.value.details or {})


def test_comments_have_no_bulk_edit(db: Db) -> None:
    with db.session() as session, pytest.raises(NotFoundError):
        bulk_apply(session, "comment", [], ALICE, set_values={"status": "open"})


def test_bulk_verification_status_with_note(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        result = bulk_apply(
            session,
            "project",
            [{"id": project_id, "expected_version": 1}],
            ALICE,
            set_values={"verification_status": "verified"},
            note="Reviewed in bulk.",
        )
        assert result.results[0].status == "updated"
        assert fields_of(session, "project", project_id)["verification_status"] == "verified"
