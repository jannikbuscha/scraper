"""Field verification (DATA_MODEL §5, §6.4)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from mdt.domain.actor import Actor
from mdt.domain.comments import create_comment
from mdt.domain.errors import (
    EntityDeletedError,
    EvidenceRequiredError,
    HasDependentsError,
    LockedFieldError,
    ValidationError,
)
from mdt.domain.revisions import apply_change, set_field_verification, soft_delete
from tests.conftest import Db
from tests.helpers import (
    USER,
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
        soft_delete(session, "evidence", deleted, USER)
        for evidence_id in (None, wrong_field, wrong_subject, deleted, "evd_unknown"):
            with pytest.raises(EvidenceRequiredError):
                set_field_verification(
                    session,
                    "project",
                    project_id,
                    "name_en",
                    "verified",
                    USER,
                    evidence_id=evidence_id,
                )
        assert load(session, "project", project_id)["version"] == 1


def test_verification_sets_status_evidence_and_lock(db: Db) -> None:
    importer = Actor.importer("example.xlsx")
    with db.session() as session:
        project_id = create_project(session, importer).entity_id
        evidence_id = create_evidence(session, project_id, "name_en").entity_id
        result = set_field_verification(
            session,
            "project",
            project_id,
            "name_en",
            "verified",
            USER,
            note="Checked",
            evidence_id=evidence_id,
        )
        assert result.changed and result.version == 2
        row = load(session, "project", project_id)
        # The entry keeps the value's provenance; the revision names the verifier.
        assert row["field_meta"]["name_en"] == {
            "src": "import:example.xlsx",
            "by": importer.by,
            "at": row["updated_at"],
            "locked": True,
            "verified": "verified",
            "evidence_id": evidence_id,
            "restored_from_version": None,
            "raw_snapshot_ids": None,
        }
        assert row["updated_by"] == USER.by
        revision = revisions_of(session, project_id)[-1]
        assert (revision.action, revision.note, revision.author) == ("verify", "Checked", USER.by)
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
            USER,
            evidence_id=evidence_id,
        )
        assert (again.changed, again.revision_id) == (False, None)
        # A value change resets the verification.
        apply_change(session, "project", project_id, {"name_en": "New"}, USER)
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
            USER,
            evidence_id=evidence_id,
        )
        with pytest.raises(ValidationError) as caught:
            set_field_verification(session, "project", project_id, "slug", "disputed", USER)
        assert caught.value.details == {"note": ["A note is required when a field is disputed"]}
        set_field_verification(
            session,
            "project",
            project_id,
            "slug",
            "disputed",
            USER,
            note="The source says otherwise.",
        )
        entry = load(session, "project", project_id)["field_meta"]["slug"]
        assert (entry["verified"], entry["evidence_id"], entry["locked"]) == (
            "disputed",
            None,
            True,
        )
        set_field_verification(session, "project", project_id, "slug", "unverified", USER)
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
            set_field_verification(session, "project", project_id, field, status, USER)
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
            USER,
        ).entity_id
        with pytest.raises(ValidationError):
            set_field_verification(
                session,
                "document",
                document_id,
                "canonical_url",
                "unverified",
                USER,
            )


def test_verification_of_deleted_rows_and_comments(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        comment_id = create_comment(session, project_id, "Example comment", USER).entity_id
        with pytest.raises(ValidationError):
            set_field_verification(session, "comment", comment_id, "body_md", "unverified", USER)
        soft_delete(session, "project", project_id, USER)
        with pytest.raises(EntityDeletedError):
            set_field_verification(session, "project", project_id, "slug", "unverified", USER)


def test_verification_locks_collector_values(db: Db) -> None:
    collector = Actor.collector("example", "run_01")
    with db.session() as session:
        project_id = apply_change(session, "project", None, project_data(), collector).entity_id
        assert load(session, "project", project_id)["field_meta"]["name_en"]["locked"] is False
        set_field_verification(session, "project", project_id, "name_en", "unverified", USER)
        entry = load(session, "project", project_id)["field_meta"]["name_en"]
        assert entry["locked"] is True and entry["src"] == "collector:example@run_01"
        with pytest.raises(LockedFieldError):
            apply_change(session, "project", project_id, {"name_en": "x"}, collector)


def _verify(session: Session, project_id: str, evidence_id: str, version: int) -> None:
    set_field_verification(
        session,
        "project",
        project_id,
        "name_en",
        "verified",
        USER,
        evidence_id=evidence_id,
    )


def test_evidence_of_a_verified_field_cannot_be_deleted(db: Db) -> None:
    # Deleting it used to leave field_meta claiming a verification whose evidence was in
    # the trash; nothing reported it.
    with db.session() as session:
        project_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "name_en").entity_id
        _verify(session, project_id, evidence_id, 1)
        for cascade in (False, True):
            with pytest.raises(HasDependentsError) as caught:
                soft_delete(session, "evidence", evidence_id, USER, cascade=cascade)
            assert caught.value.details == {"field_verification": 1}
        assert load(session, "evidence", evidence_id)["deleted_at"] is None
        assert len(revisions_of(session, evidence_id)) == 1
        # Withdrawing the verification frees the evidence.
        set_field_verification(session, "project", project_id, "name_en", "unverified", USER)
        soft_delete(session, "evidence", evidence_id, USER, note="Wrong source")
        assert load(session, "evidence", evidence_id)["deleted_at"] is not None


def test_evidence_that_no_verification_rests_on_can_be_deleted(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        used = create_evidence(session, project_id, "name_en").entity_id
        spare = create_evidence(session, project_id, "name_en").entity_id
        entity_level = create_evidence(session, project_id, "slug", target="entity").entity_id
        _verify(session, project_id, used, 1)
        soft_delete(session, "evidence", spare, USER)
        soft_delete(session, "evidence", entity_level, USER)
        # Re-verifying with other evidence moves the verification; the old row is free.
        replacement = create_evidence(session, project_id, "name_en").entity_id
        _verify(session, project_id, replacement, 2)
        soft_delete(session, "evidence", used, USER)
        # A disputed field keeps no evidence ID, so nothing blocks the delete.
        set_field_verification(
            session,
            "project",
            project_id,
            "name_en",
            "disputed",
            USER,
            note="Sources differ",
        )
        soft_delete(session, "evidence", replacement, USER)


def test_evidence_of_a_deleted_record_stays_protected(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "name_en").entity_id
        _verify(session, project_id, evidence_id, 1)
        soft_delete(session, "project", project_id, USER)
        with pytest.raises(HasDependentsError):
            soft_delete(session, "evidence", evidence_id, USER)


def test_verified_needs_evidence_with_a_verbatim_quote(db: Db) -> None:
    # CODEBOOK §2.3: "document or URL with retrieval time, plus a verbatim quote".
    with db.session() as session:
        project_id = create_project(session).entity_id
        unquoted = create_evidence(session, project_id, "name_en", quote=None).entity_id
        with pytest.raises(EvidenceRequiredError) as caught:
            _verify(session, project_id, unquoted, 1)
        assert "quote" in caught.value.message
        assert load(session, "project", project_id)["version"] == 1
        apply_change(session, "evidence", unquoted, {"quote": "Example quote."}, USER)
        _verify(session, project_id, unquoted, 1)
        assert load(session, "project", project_id)["field_meta"]["name_en"]["verified"] == (
            "verified"
        )


def test_the_quote_of_evidence_in_use_cannot_be_removed(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        used = create_evidence(session, project_id, "name_en").entity_id
        spare = create_evidence(session, project_id, "name_en").entity_id
        _verify(session, project_id, used, 1)
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "evidence", used, {"quote": None}, USER)
        assert list(caught.value.details or {}) == ["quote"]
        apply_change(session, "evidence", used, {"quote": "Other quote."}, USER)
        apply_change(session, "evidence", spare, {"quote": None}, USER)
