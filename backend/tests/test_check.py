"""The integrity report ``mdt check`` (DATA_MODEL §13)."""

from __future__ import annotations

from sqlalchemy import text

from mdt.domain.check import run_check
from mdt.domain.revisions import apply_change, set_field_verification
from tests.conftest import Db
from tests.helpers import ALICE, create_event, create_evidence, create_project, revision_count


def problems(db: Db) -> list[str]:
    with db.session() as session:
        return run_check(session, db.settings).problems


def tamper(db: Db, *statements: str, **params: str) -> None:
    db.check_on_teardown = False
    with db.engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), params)


def test_clean_database(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        create_event(session, project_id, "launch", "2013")
        before = revision_count(session)
        report = run_check(session, db.settings)
        assert report.ok and report.problems == []
        assert report.entities_checked > 2
        assert revision_count(session) == before


def test_missing_trigger(db: Db) -> None:
    tamper(db, "DROP TRIGGER revision_no_delete")
    assert problems(db) == [
        "trigger: append-only trigger revision_no_delete on revision is missing"
    ]


def test_reference_to_a_missing_row(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        event_id = create_event(session, project_id, "announced").entity_id
    tamper(
        db,
        "UPDATE event SET subject_id = 'prj_01JBX3ABCDEFGHJKMNPQRSTVWX' WHERE id = :id",
        id=event_id,
    )
    found = problems(db)
    assert (
        f"reference: {event_id}.subject_id refers to missing prj_01JBX3ABCDEFGHJKMNPQRSTVWX"
        in found
    )
    assert f"revision: {event_id} differs from its snapshot in subject_id" in found


def test_fts_rows_missing_and_orphaned(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
    tamper(
        db,
        "DELETE FROM fts_entity WHERE rowid = (SELECT rowid FROM search_key WHERE entity_id = :id)",
        id=project_id,
    )
    tamper(db, "INSERT INTO fts_entity(rowid, body) VALUES (999999, 'orphan')")
    found = problems(db)
    assert f"fts: {project_id} has no fts_entity row" in found
    assert "fts: orphaned fts_entity row 999999" in found


def test_derived_rows_missing_and_out_of_date(db: Db) -> None:
    with db.session() as session:
        first = create_project(session).entity_id
        second = create_project(session).entity_id
    tamper(db, "DELETE FROM derived WHERE entity_id = :id", id=first)
    tamper(db, "UPDATE derived SET period = 'pre_ministry' WHERE entity_id = :id", id=second)
    found = problems(db)
    assert f"derived: {first} has no derived row" in found
    assert f"derived: derived row of {second} is out of date" in found


def test_rows_that_differ_from_their_latest_snapshot(db: Db) -> None:
    with db.session() as session:
        a = create_project(session).entity_id
        b = create_project(session).entity_id
        c = create_project(session).entity_id
        d = create_project(session).entity_id
        apply_change(session, "project", d, {"name_en": "x"}, ALICE, expected_version=1)
    tamper(db, "UPDATE project SET name_en = 'Tampered' WHERE id = :id", id=a)
    tamper(db, "UPDATE project SET field_meta = '{}' WHERE id = :id", id=b)
    tamper(db, "UPDATE project SET deleted_by = 'Someone' WHERE id = :id", id=c)
    tamper(db, "UPDATE project SET version = 7 WHERE id = :id", id=d)
    found = problems(db)
    assert f"revision: {a} differs from its snapshot in name_en" in found
    assert f"revision: {b} field_meta differs from its snapshot" in found
    assert f"revision: {c} state differs from its snapshot" in found
    assert f"revision: {d} has version 7 but its latest revision is 2" in found


def test_entities_without_revision(db: Db) -> None:
    tamper(
        db,
        "INSERT INTO organization (id, version, created_at, created_by, updated_at, updated_by,"
        " name_en) VALUES ('org_01JBX3ABCDEFGHJKMNPQRSTVWX', 1, '2026-01-01T00:00:00.000000Z',"
        " 'Alice Example', '2026-01-01T00:00:00.000000Z', 'Alice Example', 'Example')",
    )
    found = problems(db)
    assert "revision: org_01JBX3ABCDEFGHJKMNPQRSTVWX has no revision" in found
    assert "fts: org_01JBX3ABCDEFGHJKMNPQRSTVWX has no search key" in found


def test_many_problems_of_one_kind_are_summarised(db: Db) -> None:
    tamper(db, "DELETE FROM fts_entity")
    found = problems(db)
    fts = [line for line in found if line.startswith("fts:")]
    assert len(fts) == 51
    assert fts[-1] == "fts: … more problems of this kind"


def test_verified_fields_whose_evidence_is_missing_deleted_or_elsewhere(db: Db) -> None:
    # The domain refuses to delete evidence that a verification rests on; the check
    # reports databases where the state arose anyway (older versions, manual edits).
    with db.session() as session:
        project_id = create_project(session).entity_id
        other_id = create_project(session).entity_id
        evidence_id = create_evidence(session, project_id, "name_en").entity_id
        slug_evidence = create_evidence(session, project_id, "slug").entity_id
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
        set_field_verification(
            session,
            "project",
            project_id,
            "slug",
            "verified",
            ALICE,
            evidence_id=slug_evidence,
            expected_version=2,
        )
        assert run_check(session, db.settings).ok
    tamper(
        db,
        "UPDATE evidence SET deleted_at = '2026-10-29T00:00:00.000000Z', deleted_by = 'x'"
        " WHERE id = :id",
        id=evidence_id,
    )
    found = problems(db)
    assert (
        f"verification: {project_id}.name_en is verified with deleted evidence {evidence_id}"
        in found
    )
    tamper(
        db,
        "UPDATE evidence SET subject_id = :other WHERE id = :id",
        other=other_id,
        id=slug_evidence,
    )
    tamper(db, "DELETE FROM evidence WHERE id = :id", id=evidence_id)
    found = problems(db)
    assert (
        f"verification: {project_id}.name_en is verified with missing evidence {evidence_id}"
        in found
    )
    assert (
        f"verification: {project_id}.slug is verified with evidence {slug_evidence} of another"
        " record or field" in found
    )
    tamper(
        db,
        "UPDATE evidence SET subject_id = :project, quote = NULL WHERE id = :id",
        project=project_id,
        id=slug_evidence,
    )
    found = problems(db)
    assert (
        f"verification: {project_id}.slug is verified with evidence {slug_evidence} without a"
        " quote" in found
    )
