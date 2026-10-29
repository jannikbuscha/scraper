"""Labels (docs/API.md §2) and revision representations (§3.2)."""

from __future__ import annotations

from mdt.db.session import read_transaction
from mdt.domain.comments import create_comment
from mdt.domain.history import latest_revision, revision_full, revision_summary
from mdt.domain.labels import entity_label, format_number, ref_info, ref_infos, refs_payload
from mdt.domain.revisions import apply_change, soft_delete
from mdt.domain.snapshots import changed_fields
from mdt.domain.vocab import TermIndex
from tests.conftest import Db
from tests.helpers import USER, create_event, create_project, create_service, project_data


def test_labels_of_every_rule(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Example project").entity_id
        uk_only = create_project(session, name_en=None, name_uk="Приклад").entity_id
        service = create_service(session, project, name_en=None, name_uk="Послуга").entity_id
        org = apply_change(
            session, "organization", None, {"name_en": "Example org"}, USER
        ).entity_id
        slug_org = apply_change(
            session, "organization", None, {"name_uk": "Організація", "slug": "org-slug"}, USER
        ).entity_id
        event = create_event(session, project, "launch", "2013-Q2").entity_id
        undated = create_event(session, service, "announced").entity_id
        document = apply_change(session, "document", None, {"title": "A title"}, USER).entity_id
        participation = apply_change(
            session,
            "participation",
            None,
            {"organization_id": org, "subject_id": project, "role": "partner"},
            USER,
        ).entity_id
        relation = apply_change(
            session,
            "relation",
            None,
            {"from_id": service, "to_id": project, "relation_type": "relates_a"},
            USER,
        ).entity_id
        indicator = apply_change(
            session,
            "indicator",
            None,
            {"subject_id": project, "metric": "Users", "value": 1500, "unit": "persons"},
            USER,
        ).entity_id
        bare_indicator = apply_change(
            session,
            "indicator",
            None,
            {"subject_id": project, "metric": "Share", "value": 0.25},
            USER,
        ).entity_id
        evidence = apply_change(
            session,
            "evidence",
            None,
            {"subject_id": event, "target": "field:date", "url": "https://example.org/e"},
            USER,
        ).entity_id
        view = apply_change(
            session,
            "saved_view",
            None,
            {"name": "My view", "entity_type": "project", "query": "sort=slug"},
            USER,
        ).entity_id
        root = create_comment(session, project, "Root", USER, field="name_en").entity_id
        entity_comment = create_comment(session, uk_only, "Root", USER).entity_id
        term = TermIndex(session).term("status", "active")
        session.rollback()
        assert term is not None
        with read_transaction(session):
            labels = {
                key: entity_label(session, entity_id)
                for key, entity_id in {
                    "project": project,
                    "uk_only": uk_only,
                    "service": service,
                    "org": org,
                    "slug_org": slug_org,
                    "event": event,
                    "undated": undated,
                    "document": document,
                    "participation": participation,
                    "relation": relation,
                    "indicator": indicator,
                    "bare_indicator": bare_indicator,
                    "evidence": evidence,
                    "view": view,
                    "root": root,
                    "entity_comment": entity_comment,
                    "term": term.id,
                }.items()
            }
    assert labels == {
        "project": "Example project",
        "uk_only": "Приклад",
        "service": "Послуга",
        "org": "Example org",
        "slug_org": "Організація",
        "event": "Example launch · Example project · 2013-Q2",
        "undated": "Example announced · Послуга · undated",
        "document": "A title",
        "participation": "Example org · Example partner · Example project",
        "relation": "Послуга Example relates_a Example project",
        "indicator": "Users: 1500 persons",
        "bare_indicator": "Share: 0.25",
        "evidence": "field:date · Example launch · Example project · 2013-Q2",
        "view": "My view",
        "root": "Comment on Example project · Name (English)",
        "entity_comment": "Comment on Приклад",
        "term": "status:active",
    }


def test_ref_infos_include_deleted_rows_and_omit_unknown_ids(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Deleted example").entity_id
        soft_delete(session, "project", project, USER)
        with read_transaction(session):
            infos = ref_infos(
                session, [project, "prj_01JBX3ABCDEFGHJKMNPQRSTVWX", None, "nonsense"]
            )
            assert set(infos) == {project}
            assert infos[project].as_dict() == {
                "id": project,
                "type": "project",
                "label": "Deleted example",
                "deleted": True,
            }
            assert ref_info(session, "nonsense") is None
            assert entity_label(session, "prj_01JBX3ABCDEFGHJKMNPQRSTVWX") == (
                "prj_01JBX3ABCDEFGHJKMNPQRSTVWX"
            )
            assert refs_payload(session, [project])[project]["deleted"] is True


def test_label_falls_back_to_the_slug_and_id(db: Db) -> None:
    with db.session() as session:
        component = apply_change(
            session, "component", None, {"name_en": "Component"}, USER
        ).entity_id
        apply_change(
            session,
            "component",
            component,
            {"name_en": None, "name_uk": "Компонент"},
            USER,
        )
        with read_transaction(session):
            assert entity_label(session, component) == "Компонент"


def test_format_number() -> None:
    assert format_number(3.0) == "3"
    assert format_number(2.5) == "2.5"
    assert format_number(7) == "7"
    assert format_number(None) == ""
    assert format_number(1e20) == "1e+20"


def test_revision_representations(db: Db) -> None:
    with db.session() as session:
        project = apply_change(session, "project", None, project_data(), USER).entity_id
        soft_delete(session, "project", project, USER, note="Gone")
        with read_transaction(session):
            revision = latest_revision(session, project)
            assert revision is not None
            summary = revision_summary(revision)
            full = revision_full(revision)
    assert set(summary) == {
        "id",
        "version",
        "at",
        "author",
        "channel",
        "action",
        "note",
        "changed_fields",
        "restored_from",
        "restored_from_version",
        "batch_id",
    }
    assert summary["changed_fields"] == ["deleted"]
    assert (summary["action"], summary["note"], summary["version"]) == ("delete", "Gone", 2)
    assert set(full) == set(summary) | {"snapshot", "diff", "schema_revision"}


def test_changed_fields() -> None:
    diff = {
        "fields": {"name_en": ["a", "b"]},
        "meta": {"name_en": {"by": ["x", "y"]}, "slug": {"verified": ["unverified", "verified"]}},
        "state": {"deleted_at": [None, "t"]},
    }
    assert changed_fields(diff) == ["name_en", "slug", "deleted"]
    assert changed_fields({}) == []
