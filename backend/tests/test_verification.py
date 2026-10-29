"""Field verification (DATA_MODEL §5, §6.4)."""

from __future__ import annotations

import pytest

from mdt.domain.actor import Actor
from mdt.domain.comments import create_comment
from mdt.domain.errors import (
    EntityDeletedError,
    EvidenceRequiredError,
    LockedFieldError,
    ValidationError,
)
from mdt.domain.revisions import apply_change, set_field_verification, soft_delete
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_evidence,
    create_project,
    load,
    project_data,
    revisions_of,
)


def test_verified_needs_matching_live_evidence(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        other_id = create_project(session).entity_id
        wrong_field = create_evidence(session, project_id, "slug").entity_id
        wrong_subject = create_evidence(session, other_id, "name_en").entity_id
        deleted = create_evidence(session, project_id, "name_en").entity_id
        soft_delete(session, "evidence", deleted, ALICE, expected_version=1)
        for evidence_id in (None, wrong_field, wrong_subject, deleted, "evd_unknown"):
            with pytest.raises(EvidenceRequiredError):
                set_field_verification(
                    session,
                    "project",
                    project_id,
                    "name_en",
                    "verified",
                    ALICE,
                    evidence_id=evidence_id,
                    expected_version=1,
                )
        assert load(session, "project", project_id)["version"] == 1


def test_verification_sets_status_evidence_and_lock(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "name_en").entity_id
        result = set_field_verification(
            session,
            "project",
            project_id,
            "name_en",
            "verified",
            BOB,
            note="Checked",
            evidence_id=evidence_id,
            expected_version=1,
        )
        assert result.changed and result.version == 2
        row = load(session, "project", project_id)
        assert row["field_meta"]["name_en"] == {
            "src": "manual:Alice Example",
            "by": ALICE.by,
            "at": row["updated_at"],
            "locked": True,
            "verified": "verified",
            "evidence_id": evidence_id,
            "restored_from_version": None,
        }
        assert row["updated_by"] == BOB.by
        revision = revisions_of(session, project_id)[-1]
        assert (revision.action, revision.note, revision.author) == ("verify", "Checked", BOB.by)
        assert revision.diff == {
            "meta": {
                "name_en": {
                    "verified": ["unverified", "verified"],
                    "evidence_id": [None, evidence_id],
                }
            }
        }
        # The same status again writes nothing.
        again = set_field_verification(
            session,
            "project",
            project_id,
            "name_en",
            "verified",
            BOB,
            evidence_id=evidence_id,
            expected_version=2,
        )
        assert (again.changed, again.revision_id) == (False, None)
        # A value change resets the verification.
        apply_change(session, "project", project_id, {"name_en": "New"}, ALICE, expected_version=2)
        entry = load(session, "project", project_id)["field_meta"]["name_en"]
        assert (entry["verified"], entry["evidence_id"]) == ("unverified", None)
    assert_matches_latest_snapshot(db, "project", project_id)


def test_disputed_needs_a_note_and_clears_the_evidence(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "slug").entity_id
        set_field_verification(
            session,
            "project",
            project_id,
            "slug",
            "verified",
            ALICE,
            evidence_id=evidence_id,
            expected_version=1,
        )
        with pytest.raises(ValidationError) as caught:
            set_field_verification(
                session, "project", project_id, "slug", "disputed", BOB, expected_version=2
            )
        assert caught.value.details == {"note": ["A note is required when a field is disputed"]}
        set_field_verification(
            session,
            "project",
            project_id,
            "slug",
            "disputed",
            BOB,
            note="The source says otherwise.",
            expected_version=2,
        )
        entry = load(session, "project", project_id)["field_meta"]["slug"]
        assert (entry["verified"], entry["evidence_id"], entry["locked"]) == (
            "disputed",
            None,
            True,
        )
        set_field_verification(
            session, "project", project_id, "slug", "unverified", BOB, expected_version=3
        )
        assert load(session, "project", project_id)["field_meta"]["slug"]["verified"] == (
            "unverified"
        )


@pytest.mark.parametrize(
    ("field", "status", "path"),
    [
        ("description_en", "unverified", "field"),  # empty
        ("verification_status", "unverified", "field"),
        ("seed_key", "unverified", "field"),  # untracked
        ("launch", "unverified", "field"),  # derived
        ("unicorn", "unverified", "field"),
        ("name_en", "approved", "status"),
    ],
)
def test_fields_that_cannot_be_verified(db: Db, field: str, status: str, path: str) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(ValidationError) as caught:
            set_field_verification(
                session, "project", project_id, field, status, ALICE, expected_version=1
            )
        assert path in (caught.value.details or {})


def test_system_fields_cannot_be_verified(db: Db) -> None:
    with db.session() as session:
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "url": "https://example.org/doc",
                "retrieved_at": "2026-10-28T10:00:00Z",
            },
            ALICE,
        ).entity_id
        with pytest.raises(ValidationError):
            set_field_verification(
                session,
                "document",
                document_id,
                "canonical_url",
                "unverified",
                ALICE,
                expected_version=1,
            )


def test_verification_of_deleted_rows_and_comments(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        comment_id = create_comment(session, project_id, "Example comment", ALICE).entity_id
        with pytest.raises(ValidationError):
            set_field_verification(
                session, "comment", comment_id, "body_md", "unverified", ALICE, expected_version=1
            )
        soft_delete(session, "project", project_id, ALICE, expected_version=1)
        with pytest.raises(EntityDeletedError):
            set_field_verification(
                session, "project", project_id, "slug", "unverified", ALICE, expected_version=2
            )


def test_verification_locks_collector_values(db: Db) -> None:
    collector = Actor.collector("example", "run_01")
    with db.session() as session:
        project_id = apply_change(session, "project", None, project_data(), collector).entity_id
        assert load(session, "project", project_id)["field_meta"]["name_en"]["locked"] is False
        set_field_verification(
            session, "project", project_id, "name_en", "unverified", ALICE, expected_version=1
        )
        entry = load(session, "project", project_id)["field_meta"]["name_en"]
        assert entry["locked"] is True and entry["src"] == "collector:example@run_01"
        with pytest.raises(LockedFieldError):
            apply_change(session, "project", project_id, {"name_en": "x"}, collector)
