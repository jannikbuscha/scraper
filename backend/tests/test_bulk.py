"""Bulk edit (DATA_MODEL §6.4, docs/API.md §3.2)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.revisions import apply_change, bulk_apply, soft_delete
from tests.conftest import Db
from tests.helpers import (
    USER,
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
        edited = create_project(session, policy_domains=["domain_c"]).entity_id
        apply_change(session, "project", edited, {"name_en": "x"}, USER)
        deleted = create_project(session).entity_id
        soft_delete(session, "project", deleted, USER)
        result = bulk_apply(
            session,
            "project",
            [updated, unchanged, edited, deleted, MISSING],
            USER,
            set_values={"status": "active"},
            add={"policy_domains": ["domain_a"]},
            note="Bulk example",
        )
        by_id = {item.id: item.as_dict() for item in result.results}
        assert by_id[updated] == {"id": updated, "status": "updated", "version": 2, "error": None}
        # Nothing differs for "unchanged" except the added domain.
        assert by_id[unchanged]["status"] == "updated"
        # A record edited before is updated from its current state.
        assert (by_id[edited]["status"], by_id[edited]["version"]) == ("updated", 3)
        assert fields_of(session, "project", edited)["policy_domains"] == [
            "domain_c",
            "domain_a",
        ]
        # A deleted record is left unchanged and reported with its version.
        assert by_id[deleted] == {
            "id": deleted,
            "status": "entity_deleted",
            "version": 2,
            "error": None,
        }
        assert fields_of(session, "project", deleted)["status"] != "active"
        assert by_id[MISSING]["status"] == "error"
        assert by_id[MISSING]["error"]["code"] == "not_found"
        for entity_id in (updated, unchanged, edited):
            revision = revisions_of(session, entity_id)[-1]
            assert (revision.batch_id, revision.note) == (result.batch_id, "Bulk example")
        again = bulk_apply(
            session,
            "project",
            [updated],
            USER,
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
            [project_id],
            USER,
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
            [good, bad],
            USER,
            set_values={"in_paper_scope": True, "scope_note": "Synthetic reason."},
        )
        assert [item.status for item in result.results] == ["updated", "updated"]
        for entity_id in (good, bad):
            assert fields_of(session, "project", entity_id)["scope_note"] == "Synthetic reason."
        # An inactive code fails per item with the error object.
        failing = bulk_apply(
            session,
            "project",
            [good],
            USER,
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
            bulk_apply(session, "project", [project_id], USER, **kwargs)
        assert path in (caught.value.details or {})
        assert len(revisions_of(session, project_id)) == 1


def test_invalid_id_lists(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        for ids, path in (
            ([], "ids"),
            ([project_id, project_id], "ids[1]"),
            ([""], "ids[0]"),
            ([f"prj_{index:026d}" for index in range(501)], "ids"),
        ):
            with pytest.raises(ValidationError) as caught:
                bulk_apply(session, "project", ids, USER, set_values={"status": "active"})
            assert path in (caught.value.details or {})
        assert len(revisions_of(session, project_id)) == 1


def test_comments_have_no_bulk_edit(db: Db) -> None:
    with db.session() as session, pytest.raises(NotFoundError):
        bulk_apply(session, "comment", [], USER, set_values={"status": "open"})


def test_bulk_verification_status_with_note(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        result = bulk_apply(
            session,
            "project",
            [project_id],
            USER,
            set_values={"verification_status": "verified"},
            note="Reviewed in bulk.",
        )
        assert result.results[0].status == "updated"
        assert fields_of(session, "project", project_id)["verification_status"] == "verified"


def test_bulk_exclusion_needs_a_reason_in_the_same_set(db: Db) -> None:
    with db.session() as session:
        unscreened = apply_change(session, "document", None, {"title": "Example A"}, USER)
        excluded = apply_change(
            session,
            "document",
            None,
            {"title": "Example B", "screening_status": "excluded", "screening_reason": "reason_a"},
            USER,
        )
        items = [unscreened.entity_id, excluded.entity_id]
        with pytest.raises(ValidationError) as caught:
            bulk_apply(
                session, "document", items, USER, set_values={"screening_status": "excluded"}
            )
        assert list(caught.value.details or {}) == ["set.screening_reason"]
        result = bulk_apply(
            session,
            "document",
            items,
            USER,
            set_values={"screening_status": "excluded", "screening_reason": "reason_b"},
        )
        assert [item.status for item in result.results] == ["updated", "updated"]
        # Including keeps the per-record rule: the reason has to go in the same change.
        result = bulk_apply(
            session, "document", items, USER, set_values={"screening_status": "included"}
        )
        assert [item.status for item in result.results] == ["error", "error"]
        assert result.results[0].error is not None
        assert result.results[0].error["details"] == {
            "screening_reason": ["is allowed only for excluded documents"]
        }
        result = bulk_apply(
            session,
            "document",
            items,
            USER,
            set_values={"screening_status": "included", "screening_reason": None},
        )
        assert [item.status for item in result.results] == ["updated", "updated"]
