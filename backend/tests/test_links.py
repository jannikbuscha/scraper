"""Document links: the ``links`` field of documents (DATA_MODEL §1.2, §2.1, §4)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from mdt.db.models import DocumentLink
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import ConflictError, ReferenceDeletedError, ValidationError
from mdt.domain.revisions import apply_change, restore_version, soft_delete
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_project,
    create_service,
    fields_of,
    revisions_of,
)

COLLECTOR = Actor.collector("example", "run_01")


def link_rows(db: Db, document_id: str) -> list[dict[str, Any]]:
    with db.session() as session, read_transaction(session):
        rows = session.scalars(
            select(DocumentLink)
            .where(DocumentLink.document_id == document_id)
            .order_by(DocumentLink.subject_id)
        ).all()
        return [
            {
                "subject_id": row.subject_id,
                "origin": row.origin,
                "state": row.state,
                "matched_aliases": row.matched_aliases,
                "match_count": row.match_count,
                "snippet": row.snippet,
            }
            for row in rows
        ]


def test_links_are_stored_snapshotted_and_restored(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        service_id = create_service(session, project_id).entity_id
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "links": [
                    {"subject_id": service_id, "state": "suggested", "origin": "auto"},
                    {
                        "subject_id": project_id,
                        "state": "confirmed",
                        "match_count": 9,
                        "snippet": "forged",
                    },
                ],
            },
            ALICE,
        ).entity_id
        expected: list[dict[str, Any]] = sorted(
            [
                {
                    "subject_id": project_id,
                    "origin": "manual",
                    "state": "confirmed",
                    "matched_aliases": [],
                    "match_count": 0,
                    "snippet": None,
                },
                {
                    "subject_id": service_id,
                    "origin": "manual",  # people cannot claim an automatic origin
                    "state": "suggested",
                    "matched_aliases": [],
                    "match_count": 0,
                    "snippet": None,
                },
            ],
            key=lambda link: str(link["subject_id"]),
        )
        assert link_rows(db, document_id) == expected
        assert fields_of(session, "document", document_id)["links"] == expected
        assert revisions_of(session, document_id)[0].snapshot["fields"]["links"] == expected
        # Changing a state, then removing a link.
        apply_change(
            session,
            "document",
            document_id,
            {"links": [{"subject_id": project_id, "state": "rejected"}]},
            BOB,
            expected_version=1,
        )
        assert [link["state"] for link in link_rows(db, document_id)] == ["rejected"]
        revision = revisions_of(session, document_id)[-1]
        assert set(revision.diff["fields"]) == {"links"}
        restore_version(session, "document", document_id, 1, BOB, expected_version=2)
        assert link_rows(db, document_id) == expected
    assert_matches_latest_snapshot(db, "document", document_id)


def test_collectors_create_automatic_links_with_match_details(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "links": [
                    {
                        "subject_id": project_id,
                        "state": "suggested",
                        "matched_aliases": ["Example"],
                        "match_count": 2,
                        "snippet": "an Example mention",
                    }
                ],
            },
            COLLECTOR,
        ).entity_id
        [link] = link_rows(db, document_id)
        assert (link["origin"], link["matched_aliases"], link["match_count"], link["snippet"]) == (
            "auto",
            ["Example"],
            2,
            "an Example mention",
        )
        # A person confirms it: the origin and the match details stay.
        apply_change(
            session,
            "document",
            document_id,
            {"links": [{"subject_id": project_id, "state": "confirmed", "origin": "manual"}]},
            ALICE,
            expected_version=1,
        )
        [link] = link_rows(db, document_id)
        assert (link["origin"], link["state"], link["match_count"]) == ("auto", "confirmed", 2)


def test_link_subjects_are_checked(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Linked project").entity_id
        base = {"title": "Example document"}
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "document",
                None,
                {
                    **base,
                    "links": [
                        {"subject_id": "prj_01JBX3ABCDEFGHJKMNPQRSTVWX", "state": "suggested"}
                    ],
                },
                ALICE,
            )
        assert caught.value.details == {
            "links[0].subject_id": ["refers to a record that does not exist"]
        }
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "document",
                None,
                {
                    **base,
                    "links": [
                        {"subject_id": "org_01JBX3ABCDEFGHJKMNPQRSTVWX", "state": "suggested"}
                    ],
                },
                ALICE,
            )
        document_id = apply_change(
            session,
            "document",
            None,
            {**base, "links": [{"subject_id": project_id, "state": "suggested"}]},
            ALICE,
        ).entity_id
        soft_delete(session, "project", project_id, ALICE, expected_version=1)
        # A kept link to a deleted subject does not block other changes ...
        apply_change(
            session, "document", document_id, {"title": "Renamed"}, ALICE, expected_version=1
        )
        # ... but a new link to a deleted subject does.
        other = apply_change(session, "document", None, base, ALICE).entity_id
        with pytest.raises(ReferenceDeletedError) as reference:
            apply_change(
                session,
                "document",
                other,
                {"links": [{"subject_id": project_id, "state": "suggested"}]},
                ALICE,
                expected_version=1,
            )
        assert reference.value.details is not None
        assert reference.value.details["field"] == "links"


def test_conflict_payload_labels_link_subjects(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Linked project").entity_id
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "links": [{"subject_id": project_id, "state": "suggested"}],
            },
            ALICE,
        ).entity_id
        apply_change(session, "document", document_id, {"title": "x"}, BOB, expected_version=1)
        with pytest.raises(ConflictError) as caught:
            apply_change(
                session, "document", document_id, {"title": "y"}, ALICE, expected_version=1
            )
        assert caught.value.payload["refs"][project_id]["label"] == "Linked project"


def test_restore_brings_back_links_as_recorded(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "links": [
                    {
                        "subject_id": project_id,
                        "state": "suggested",
                        "matched_aliases": ["Example"],
                        "match_count": 3,
                        "snippet": "Example snippet",
                    }
                ],
            },
            COLLECTOR,
        ).entity_id
        recorded = link_rows(db, document_id)
        apply_change(session, "document", document_id, {"links": []}, ALICE, expected_version=1)
        assert link_rows(db, document_id) == []
        restore_version(session, "document", document_id, 1, BOB, expected_version=2)
        assert link_rows(db, document_id) == recorded
        assert recorded[0]["origin"] == "auto"
    assert_matches_latest_snapshot(db, "document", document_id)
