"""The Phase 2 checks of ``mdt check`` (docs/DATA_MODEL.md §13): references to raw snapshots
and document texts, records named by observations and open proposals, merged records; and
fields that an older snapshot does not record while they are still empty."""

from __future__ import annotations

from sqlalchemy import insert, text, update

from mdt.db.ddl import create_revision_triggers
from mdt.db.models import Document, Project, SourceObservation
from mdt.db.session import write_transaction
from mdt.domain.actor import Actor
from mdt.domain.check import run_check
from mdt.domain.proposals import ProposalDraft, raise_proposal
from mdt.domain.revisions import apply_change
from mdt.domain.run_effects import RunEffects
from tests.conftest import Db
from tests.domain_p2.conftest import P2
from tests.helpers import create_project

USER = Actor.ui()
MISSING = "prj_01JBX3EXAMPLE0000000000000"


def problems(db: Db) -> list[str]:
    with db.session() as session:
        return run_check(session, db.settings).problems


def test_a_field_missing_from_an_older_snapshot_is_fine_while_empty(db: Db) -> None:
    with db.session() as session:
        document = apply_change(session, "document", None, {"title": "Example"}, USER).entity_id
    with db.engine.begin() as connection:  # the snapshot as written before migration 0002
        connection.execute(text("DROP TRIGGER revision_no_update"))
        connection.execute(
            text(
                "UPDATE revision SET snapshot = json_remove(snapshot, '$.fields.source_record_at') "
                "WHERE entity_id = :id"
            ),
            {"id": document},
        )
        create_revision_triggers(connection)
    assert problems(db) == []
    with db.session() as session, write_transaction(session):
        session.execute(
            update(Document)
            .where(Document.id == document)
            .values(source_record_at="2025-01-01T00:00:00.000000Z")
        )
    assert any("source_record_at" in line for line in problems(db))
    db.check_on_teardown = False


def test_missing_raw_snapshots_and_texts_are_reported(p2: P2) -> None:
    with p2.session() as session:
        project = create_project(session).entity_id
        document = apply_change(session, "document", None, {"title": "Example"}, USER).entity_id
    with p2.session() as session, write_transaction(session):
        session.execute(
            update(Project)
            .where(Project.id == project)
            .values(field_meta={"name_en": {"src": "seed", "raw_snapshot_ids": ["raw_missing"]}})
        )
        session.execute(
            update(Document)
            .where(Document.id == document)
            .values(text_hash="0" * 64, raw_snapshot_id="raw_gone")
        )
    found = problems(p2.db)
    assert f"reference: {project}.name_en names missing raw snapshot raw_missing" in found
    assert f"reference: document {document} refers to missing raw snapshot raw_gone" in found
    assert f"reference: {document} has no document text {'0' * 64}" in found
    p2.db.check_on_teardown = False


def test_observations_and_open_proposals_of_missing_records_are_reported(p2: P2) -> None:
    run_id = p2.new_run()
    with p2.session() as session, write_transaction(session):
        now = "2026-01-01T00:00:00.000000Z"
        session.execute(
            insert(SourceObservation).values(
                collector="stub",
                key="entry:x",
                entity_type="project",
                subject_id=MISSING,
                first_seen_at=now,
                first_seen_run=run_id,
                last_seen_at=now,
                last_seen_run=run_id,
            )
        )
        raise_proposal(
            session,
            ProposalDraft(
                kind="update_field",
                entity_type="project",
                collector="stub",
                target=MISSING,
                core=["notes", "x"],
                subject_id=MISSING,
                field="notes",
                proposed_value="x",
            ),
            run_id=run_id,
            now=now,
            effects=RunEffects(),
        )
    found = problems(p2.db)
    assert any(line.startswith("reference: observation") and MISSING in line for line in found)
    assert any(line.startswith("reference: open proposal") and MISSING in line for line in found)
    p2.db.check_on_teardown = False


def test_merged_records_must_be_deleted_and_name_a_survivor(db: Db) -> None:
    with db.session() as session:
        project = create_project(session).entity_id
    with db.session() as session, write_transaction(session):
        session.execute(update(Project).where(Project.id == project).values(merged_into=MISSING))
    found = problems(db)
    assert f"merge: {project} is merged into {MISSING} but not deleted" in found
    assert f"merge: {project} is merged into missing {MISSING}" in found
    db.check_on_teardown = False
