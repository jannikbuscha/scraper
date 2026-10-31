"""Restore of old versions (DATA_MODEL §5, §6.4) and diffs between versions (§6.3)."""

from __future__ import annotations

import pytest

from mdt.domain.actor import Actor
from mdt.domain.comments import create_comment, edit_comment
from mdt.domain.errors import (
    EntityDeletedError,
    NotFoundError,
    ReferenceDeletedError,
    UniqueViolationError,
    ValidationError,
)
from mdt.domain.history import diff_versions
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.revisions import (
    _restore_plan,
    apply_change,
    restore_version,
    set_field_verification,
    soft_delete,
)
from mdt.domain.snapshots import diff_snapshots
from mdt.domain.vocab import TermIndex
from tests.conftest import Db
from tests.helpers import (
    USER,
    assert_matches_latest_snapshot,
    create_evidence,
    create_project,
    create_service,
    fields_of,
    load,
    revisions_of,
)

PROJECT = ENTITY_TYPES["project"]


def _two_versions(db: Db) -> str:
    with db.session() as session:
        project_id = create_project(session, name_en="Version one", status="planned").entity_id
        apply_change(
            session,
            "project",
            project_id,
            {"name_en": "Version two", "status": "active", "notes": "Added later."},
            USER,
        )
    return project_id


def test_restore_applies_the_old_values_with_provenance(db: Db) -> None:
    with db.session() as session:
        importer = Actor.importer("example.xlsx")
        project_id = create_project(
            session, importer, name_en="Version one", status="planned"
        ).entity_id
        apply_change(
            session,
            "project",
            project_id,
            {"name_en": "Version two", "status": "active", "notes": "Added later."},
            USER,
        )
        first_revision = revisions_of(session, project_id)[0]
        result = restore_version(
            session,
            "project",
            project_id,
            1,
            USER,
            note="Back to the first version",
        )
        assert result.changed and result.version == 3
        assert result.changes == {
            "name_en": ["Version two", "Version one"],
            "notes": ["Added later.", None],
            "status": ["active", "planned"],
        }
        assert result.skipped_fields == [] and result.warnings == []
        row = load(session, "project", project_id)
        assert (row["name_en"], row["status"], row["notes"]) == ("Version one", "planned", None)
        ts = row["updated_at"]
        meta = row["field_meta"]
        assert meta["name_en"] == {
            "src": "import:example.xlsx",  # the source of the restored value
            "by": USER.by,
            "at": ts,
            "locked": True,
            "verified": "unverified",
            "evidence_id": None,
            "restored_from_version": 1,
            "raw_snapshot_ids": None,
        }
        assert meta["notes"]["src"] == "manual"  # no entry in version 1
        assert meta["notes"]["restored_from_version"] == 1
        revision = revisions_of(session, project_id)[-1]
        assert (revision.action, revision.channel, revision.author, revision.note) == (
            "restore",
            "restore",
            USER.by,
            "Back to the first version",
        )
        assert (revision.restored_from, revision.restored_from_version) == (first_revision.id, 1)
        # A later value change clears restored_from_version again.
        apply_change(session, "project", project_id, {"name_en": "Edited"}, USER)
        assert (
            load(session, "project", project_id)["field_meta"]["name_en"]["restored_from_version"]
            is None
        )
    assert_matches_latest_snapshot(db, "project", project_id)


def test_dry_run_and_field_selection(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        preview = restore_version(session, "project", project_id, 1, USER, dry_run=True)
        assert preview.dry_run and not preview.changed and preview.revision_id is None
        assert set(preview.changes) == {"name_en", "notes", "status"}
        assert load(session, "project", project_id)["version"] == 2
        partial = restore_version(session, "project", project_id, 1, USER, fields=["name_en"])
        assert partial.changes == {"name_en": ["Version two", "Version one"]}
        fields = fields_of(session, "project", project_id)
        assert (fields["name_en"], fields["status"]) == ("Version one", "active")
        with pytest.raises(ValidationError):
            restore_version(session, "project", project_id, 1, USER, fields=["unicorn"])
        with pytest.raises(ValidationError):
            restore_version(
                session,
                "project",
                project_id,
                1,
                USER,
                fields="name_en",
            )


def test_restoring_the_current_state_is_a_no_op(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        result = restore_version(session, "project", project_id, 2, USER)
        assert (result.changed, result.revision_id, result.changes) == (False, None, {})
        assert len(revisions_of(session, project_id)) == 2


def test_restore_resets_field_verification(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        evidence = create_evidence(session, project_id, "name_en")
        set_field_verification(
            session,
            "project",
            project_id,
            "name_en",
            "verified",
            USER,
            evidence_id=evidence.entity_id,
        )
        restore_version(session, "project", project_id, 1, USER)
        entry = load(session, "project", project_id)["field_meta"]["name_en"]
        assert (entry["verified"], entry["evidence_id"], entry["restored_from_version"]) == (
            "unverified",
            None,
            1,
        )


def test_restore_reports_unique_violations(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, slug="example-restore").entity_id
        apply_change(session, "project", project_id, {"slug": "example-renamed"}, USER)
        create_project(session, slug="example-restore")
        with pytest.raises(UniqueViolationError) as caught:
            restore_version(session, "project", project_id, 1, USER)
        assert caught.value.details is not None and caught.value.details["field"] == "slug"
        assert load(session, "project", project_id)["version"] == 2


def test_restore_reports_deleted_references(db: Db) -> None:
    with db.session() as session:
        first = create_project(session, name_en="First").entity_id
        second = create_project(session).entity_id
        service_id = create_service(session, first).entity_id
        apply_change(session, "service", service_id, {"project_id": second}, USER)
        soft_delete(session, "project", first, USER)
        with pytest.raises(ReferenceDeletedError) as caught:
            restore_version(session, "service", service_id, 1, USER)
        assert caught.value.details == {
            "field": "project_id",
            "id": first,
            "type": "project",
            "label": "First",
        }


def test_restore_is_refused_on_deleted_entities(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        soft_delete(session, "project", project_id, USER)
        with pytest.raises(EntityDeletedError):
            restore_version(session, "project", project_id, 1, USER)


def test_restore_accepts_inactive_codes_with_a_warning(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        planned = TermIndex(session).term("status", "planned")
        session.rollback()
        assert planned is not None
        apply_change(session, "vocabulary_term", planned.id, {"active": False}, USER)
        result = restore_version(session, "project", project_id, 1, USER)
        assert [w.as_dict() for w in result.warnings] == [
            {
                "code": "inactive_code",
                "message": "An inactive code was restored; it cannot be newly assigned.",
                "field": "status",
            }
        ]
        assert fields_of(session, "project", project_id)["status"] == "planned"
        # Channel ui still refuses the inactive code.
        other_id = create_project(session).entity_id
        with pytest.raises(ValidationError):
            apply_change(session, "project", other_id, {"status": "planned"}, USER)


def test_restore_keeps_state_and_recomputes_system_fields(db: Db) -> None:
    with db.session() as session:
        document_id = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "url": "https://example.org/one/",
                "retrieved_at": "2026-10-28T10:00:00Z",
            },
            USER,
        ).entity_id
        apply_change(
            session,
            "document",
            document_id,
            {"url": "https://example.org/two"},
            USER,
        )
        result = restore_version(session, "document", document_id, 1, USER)
        assert "canonical_url" not in result.changes  # recomputed, not restored
        row = load(session, "document", document_id)
        assert (row["url"], row["canonical_url"]) == (
            "https://example.org/one/",
            "https://example.org/one",
        )
        assert row["field_meta"]["canonical_url"] == row["field_meta"]["url"]
    assert_matches_latest_snapshot(db, "document", document_id)


def test_create_only_fields_are_skipped(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "slug").entity_id
        apply_change(session, "evidence", evidence_id, {"quote": "Changed quote."}, USER)
        result = restore_version(
            session,
            "evidence",
            evidence_id,
            1,
            USER,
            fields=["quote", "target", "created_at"],
        )
        assert result.changes == {"quote": ["Changed quote.", "Example quote."]}
        assert result.skipped_fields == ["created_at", "target"]


def test_restoring_the_scope_needs_its_note(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, scope_note="Out of scope at first.").entity_id
        apply_change(
            session,
            "project",
            project_id,
            {"in_paper_scope": True, "scope_note": "In scope now."},
            USER,
        )
        with pytest.raises(ValidationError):
            restore_version(
                session,
                "project",
                project_id,
                1,
                USER,
                fields=["in_paper_scope"],
            )
        result = restore_version(session, "project", project_id, 1, USER)
        assert set(result.changes) == {"in_paper_scope", "scope_note"}


def test_restore_errors(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        with pytest.raises(NotFoundError):
            restore_version(session, "project", project_id, 9, USER)
        with pytest.raises(ValidationError):
            restore_version(
                session,
                "project",
                project_id,
                1,
                Actor.collector("example", "run_01"),
            )


def test_comment_bodies_can_be_restored(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        comment_id = create_comment(session, project_id, "Original text", USER).entity_id
        edit_comment(session, comment_id, "Edited text", USER)
        result = restore_version(session, "comment", comment_id, 1, USER)
        assert result.changes == {"body_md": ["Edited text", "Original text"]}
        assert load(session, "comment", comment_id)["body_md"] == "Original text"
        assert revisions_of(session, comment_id)[-1].snapshot["field_meta"] == {}
    assert_matches_latest_snapshot(db, "comment", comment_id)


# --------------------------------------------------------------------------------------
# Snapshots from older schemas and diffs between versions
# --------------------------------------------------------------------------------------


def test_fields_missing_from_an_old_snapshot_are_left_unchanged() -> None:
    current = {field.name: field.empty_value() for field in PROJECT.tracked_fields}
    current.update({"name_en": "Current", "notes": "Current note."})
    old_snapshot = {"fields": {"name_en": "Old"}, "field_meta": {}, "state": {}}
    provided, changes, skipped = _restore_plan(PROJECT, old_snapshot, current, None)
    assert provided == {"name_en": "Old"} and changes == {"name_en": ["Current", "Old"]}
    assert skipped == []
    provided, changes, skipped = _restore_plan(PROJECT, old_snapshot, current, ["notes"])
    assert (provided, changes, skipped) == ({}, {}, ["notes"])


def test_diff_between_versions(db: Db) -> None:
    project_id = _two_versions(db)
    with db.session() as session:
        soft_delete(session, "project", project_id, USER)
        diff, not_recorded = diff_versions(session, PROJECT, project_id, 1, 3)
        assert not_recorded == []
        assert diff["fields"] == {
            "name_en": ["Version one", "Version two"],
            "status": ["planned", "active"],
            "notes": [None, "Added later."],
        }
        # name_en and status kept their source and author; only notes got a new entry.
        assert set(diff["meta"]) == {"notes"}
        assert diff["state"]["deleted_by"] == [None, USER.by]
        from_zero, _ = diff_versions(session, PROJECT, project_id, 0, 1)
        assert from_zero == {"fields": revisions_of(session, project_id)[0].diff["fields"]}
        with pytest.raises(ValidationError):
            diff_versions(session, PROJECT, project_id, 2, 2)
        with pytest.raises(NotFoundError):
            diff_versions(session, PROJECT, project_id, 1, 9)


def test_diff_marks_fields_that_an_old_snapshot_did_not_record() -> None:
    old = {"fields": {"name_en": "A"}, "field_meta": {}, "state": {}}
    new = {"fields": {"name_en": "B", "notes": "N"}, "field_meta": {}, "state": {}}
    diff, not_recorded = diff_snapshots(PROJECT, old, new)
    assert diff == {"fields": {"name_en": ["A", "B"]}}
    assert not_recorded == ["notes"]
