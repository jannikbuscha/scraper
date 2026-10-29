"""Soft delete, cascade and undelete (DATA_MODEL §6.4)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.db.models import Derived
from mdt.db.session import read_transaction
from mdt.domain.comments import create_comment
from mdt.domain.errors import (
    HasDependentsError,
    InvalidStateError,
    NotDeletableError,
    ReferenceDeletedError,
    UniqueViolationError,
)
from mdt.domain.revisions import apply_change, soft_delete, undelete
from mdt.domain.vocab import TermIndex
from mdt.domain.writes import write_state_change
from tests.conftest import Db
from tests.helpers import (
    USER,
    assert_matches_latest_snapshot,
    create_event,
    create_evidence,
    create_project,
    create_service,
    fts_row,
    load,
    revisions_of,
)


def test_soft_delete_keeps_the_row_and_writes_a_state_revision(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        result = soft_delete(session, "project", project_id, USER, note="Duplicate")
        assert result.changed and result.version == 2 and result.batch_id
        row = load(session, "project", project_id)
        assert row["deleted_by"] == USER.by and row["deleted_at"] == row["updated_at"]
        revision = revisions_of(session, project_id)[-1]
        assert (revision.action, revision.note, revision.batch_id) == (
            "delete",
            "Duplicate",
            result.batch_id,
        )
        assert revision.diff == {
            "state": {"deleted_at": [None, row["deleted_at"]], "deleted_by": [None, USER.by]}
        }
        # The FTS row and the derived row are kept for the trash.
        assert fts_row(session, project_id) is not None
        with read_transaction(session):
            assert session.get(Derived, project_id) is not None
    assert_matches_latest_snapshot(db, "project", project_id)


def test_deleting_twice_is_an_invalid_state(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        soft_delete(session, "project", project_id, USER)
        with pytest.raises(InvalidStateError) as caught:
            soft_delete(session, "project", project_id, USER)
        assert caught.value.details == {"state": "deleted"}


def test_vocabulary_terms_cannot_be_deleted(db: Db) -> None:
    with db.session() as session:
        term = TermIndex(session).term("status", "active")
        session.rollback()
        assert term is not None
        with pytest.raises(NotDeletableError):
            soft_delete(session, "vocabulary_term", term.id, USER)


def test_project_with_services_needs_cascade(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        parent = create_service(session, project_id).entity_id
        child = create_service(session, project_id, parent_service_id=parent).entity_id
        gone = create_service(session, project_id).entity_id
        soft_delete(session, "service", gone, USER)
        event_id = create_event(session, project_id, "announced").entity_id
        evidence_id = create_evidence(session, project_id, "slug").entity_id
        comment_id = create_comment(session, project_id, "Example comment", USER).entity_id
        with pytest.raises(HasDependentsError) as caught:
            soft_delete(session, "project", project_id, USER)
        assert caught.value.details == {"service": 2}
        assert load(session, "project", project_id)["deleted_at"] is None
        result = soft_delete(session, "project", project_id, USER, note="Cascade", cascade=True)
        for service_id in (parent, child):
            row = load(session, "service", service_id)
            assert row["deleted_at"] is not None
            revision = revisions_of(session, service_id)[-1]
            assert (revision.action, revision.batch_id, revision.note) == (
                "delete",
                result.batch_id,
                "Cascade",
            )
        # The separately deleted service keeps its own batch.
        assert revisions_of(session, gone)[-1].batch_id != result.batch_id
        # Events, evidence and comments are never deleted with it.
        for entity_type, entity_id in (
            ("event", event_id),
            ("evidence", evidence_id),
            ("comment", comment_id),
        ):
            assert load(session, entity_type, entity_id)["deleted_at"] is None
    for service_id in (parent, child):
        assert_matches_latest_snapshot(db, "service", service_id)


def test_service_with_child_services_needs_cascade(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        parent = create_service(session, project_id).entity_id
        child = create_service(session, project_id, parent_service_id=parent).entity_id
        grandchild = create_service(session, project_id, parent_service_id=child).entity_id
        with pytest.raises(HasDependentsError) as caught:
            soft_delete(session, "service", parent, USER)
        assert caught.value.details == {"service": 2}
        soft_delete(session, "service", parent, USER, cascade=True)
        assert all(
            load(session, "service", service_id)["deleted_at"] is not None
            for service_id in (parent, child, grandchild)
        )
        assert load(session, "project", project_id)["deleted_at"] is None


def test_cascade_is_all_or_nothing(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    original = write_state_change
    calls: list[str] = []

    def failing(*args: Any, **kwargs: Any) -> Any:
        calls.append("call")
        if len(calls) == 3:
            raise RuntimeError("simulated failure in the middle of a cascade")
        return original(*args, **kwargs)

    with db.session() as session:
        project_id = create_project(session).entity_id
        services = [create_service(session, project_id).entity_id for _ in range(3)]
        monkeypatch.setattr("mdt.domain.revisions.write_state_change", failing)
        with pytest.raises(RuntimeError):
            soft_delete(session, "project", project_id, USER, cascade=True)
        monkeypatch.undo()
        assert load(session, "project", project_id)["deleted_at"] is None
        for service_id in services:
            row = load(session, "service", service_id)
            assert (row["deleted_at"], row["version"]) == (None, 1)
            assert len(revisions_of(session, service_id)) == 1


def test_undelete(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(InvalidStateError) as caught:
            undelete(session, "project", project_id, USER)
        assert caught.value.details == {"state": "live"}
        soft_delete(session, "project", project_id, USER)
        result = undelete(session, "project", project_id, USER, note="Restored")
        assert result.version == 3 and result.batch_id
        row = load(session, "project", project_id)
        assert (row["deleted_at"], row["deleted_by"], row["updated_by"]) == (None, None, USER.by)
        revision = revisions_of(session, project_id)[-1]
        assert (revision.action, revision.note) == ("undelete", "Restored")
        assert set(revision.diff) == {"state"}
    assert_matches_latest_snapshot(db, "project", project_id)


def test_undelete_cascade_restores_the_batch_only(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        earlier = create_service(session, project_id).entity_id
        soft_delete(session, "service", earlier, USER)
        cascaded = [create_service(session, project_id).entity_id for _ in range(2)]
        soft_delete(session, "project", project_id, USER, cascade=True)
        # Without cascade only the project comes back.
        undelete(session, "project", project_id, USER)
        assert all(load(session, "service", s)["deleted_at"] for s in cascaded)
        soft_delete(session, "project", project_id, USER)
        # The services' latest revision is still the first cascade, not this delete.
        undelete(session, "project", project_id, USER, cascade=True)
        assert all(load(session, "service", s)["deleted_at"] for s in cascaded)
        # A fresh cascade comes back as a whole; the earlier deletion stays.
        for service_id in cascaded:
            undelete(session, "service", service_id, USER)
        soft_delete(session, "project", project_id, USER, cascade=True)
        result = undelete(session, "project", project_id, USER, cascade=True)
        for service_id in cascaded:
            assert load(session, "service", service_id)["deleted_at"] is None
            revision = revisions_of(session, service_id)[-1]
            assert (revision.action, revision.batch_id) == ("undelete", result.batch_id)
        assert load(session, "service", earlier)["deleted_at"] is not None


def test_undelete_revalidates_uniqueness(db: Db) -> None:
    with db.session() as session:
        data = {
            "title": "Example document",
            "url": "https://example.org/doc",
            "retrieved_at": "2026-10-28T10:00:00Z",
        }
        first = apply_change(session, "document", None, data, USER).entity_id
        soft_delete(session, "document", first, USER)
        apply_change(session, "document", None, data, USER)
        with pytest.raises(UniqueViolationError) as caught:
            undelete(session, "document", first, USER)
        assert caught.value.details is not None
        assert caught.value.details["field"] == "canonical_url"
        assert load(session, "document", first)["deleted_at"] is not None


def test_undelete_revalidates_required_references(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Parent project").entity_id
        service_id = create_service(session, project_id).entity_id
        soft_delete(session, "service", service_id, USER)
        soft_delete(session, "project", project_id, USER)
        with pytest.raises(ReferenceDeletedError) as caught:
            undelete(session, "service", service_id, USER)
        assert caught.value.details == {
            "field": "project_id",
            "id": project_id,
            "type": "project",
            "label": "Parent project",
        }
        undelete(session, "project", project_id, USER)
        undelete(session, "service", service_id, USER)
