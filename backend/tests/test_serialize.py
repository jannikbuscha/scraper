"""Item, comment and revision representations (docs/API.md §2, §3.2, §3.3)."""

from __future__ import annotations

from typing import Any

import pytest

from mdt.domain.actor import Actor
from mdt.domain.comments import create_comment, delete_comment, edit_comment, resolve_comment
from mdt.domain.errors import NotFoundError
from mdt.domain.query import list_entities
from mdt.domain.registry import ENTITY_TYPES, SERVICE
from mdt.domain.revisions import apply_change, soft_delete
from mdt.domain.serialize import (
    diff_ref_ids,
    field_ref_ids,
    get_comment,
    get_item,
)
from tests.conftest import Db
from tests.helpers import (
    USER,
    create_event,
    create_evidence,
    create_project,
    create_service,
    focal_org_id,
)
from tests.read_helpers import create, create_document

ITEM_KEYS = {
    "id",
    "type",
    "label",
    "version",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "merged_into",
    "fields",
    "field_meta",
    "virtual",
    "refs",
    "search_snippet",
}
DERIVED_KEYS = {
    "launch",
    "launch_start",
    "launch_end",
    "launch_precision",
    "launch_basis",
    "launch_event_id",
    "existed_by",
    "existed_by_event_id",
    "existed_before_invasion",
    "period",
    "period_reason",
    "war_trajectory",
    "trajectory_reason",
    "trajectory_event_id",
    "portfolio_entry",
    "portfolio_entry_start",
    "portfolio_entry_end",
    "portfolio_entry_precision",
    "portfolio_entry_participation_id",
    "computed_at",
}
COMMENT_KEYS = {
    "id",
    "subject_id",
    "subject_type",
    "subject_label",
    "field",
    "parent_id",
    "body_md",
    "body_html",
    "status",
    "resolved_by",
    "resolved_at",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "version",
    "edited",
    "deleted_at",
    "deleted_by",
}


def item(session: Any, entity_type: str, entity_id: str) -> dict[str, Any]:
    return get_item(session, entity_type, entity_id)


def label(session: Any, entity_type: str, entity_id: str) -> str:
    return str(item(session, entity_type, entity_id)["label"])


# --------------------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------------------


def test_project_item_shape(db: Db) -> None:
    with db.session() as session:
        project = apply_change(
            session,
            "project",
            None,
            {
                "slug": "seeded-example",
                "seed_key": "seeded-example",
                "name_en": "Seeded example",
                "scope_note": "Synthetic.",
            },
            Actor.seed(),
        )
        result = item(session, "project", project.entity_id)
    assert set(result) == ITEM_KEYS | {"derived"}
    assert result["type"] == "project"
    assert result["label"] == "Seeded example"
    assert result["version"] == 1
    assert (result["created_by"], result["updated_by"]) == ("seed", "seed")
    fields = result["fields"]
    assert set(fields) == {field.name for field in ENTITY_TYPES["project"].api_fields}
    assert "seed_key" not in fields and "created_at" not in fields and "launch" not in fields
    assert fields["in_paper_scope"] is False
    assert fields["verification_status"] == "unverified"
    assert fields["aliases"] == [] and fields["policy_domains"] == []
    assert result["field_meta"]["name_en"]["src"] == "seed"
    assert set(result["derived"]) == DERIVED_KEYS
    assert result["derived"]["period"] == "unknown"
    assert result["derived"]["period_reason"] == "no_date"
    assert result["virtual"] == {
        "open_comments": 0,
        "comment_count": 0,
        "open_comments_by_field": {},
    }
    assert result["refs"] == {}
    assert result["search_snippet"] is None


def test_list_items_omit_detail_only_values(db: Db) -> None:
    with db.session() as session:
        create_project(session)
        listed = list_entities(session, "project", {})["items"][0]
    assert "open_comments_by_field" not in listed["virtual"]
    assert set(listed) == ITEM_KEYS | {"derived"}


@pytest.mark.parametrize("entity_type", ["event", "document", "organization", "evidence"])
def test_only_projects_and_services_have_derived(entity_type: str) -> None:
    assert ENTITY_TYPES[entity_type].has_derived is False


def test_service_item_refs_virtual_and_derived(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session, name_en="Parent project", in_paper_scope=True, scope_note="In scope."
        ).entity_id
        parent = create_service(session, project, name_en="Parent service").entity_id
        child = create_service(
            session, project, name_en=None, name_uk="Дочірня", parent_service_id=parent
        )
        result = item(session, "service", child.entity_id)
    assert result["label"] == "Дочірня"
    assert result["refs"]["project_id"] == {
        "id": project,
        "type": "project",
        "label": "Parent project",
        "deleted": False,
    }
    assert result["refs"]["parent_service_id"]["label"] == "Parent service"
    assert result["virtual"]["project_in_paper_scope"] is True
    assert set(result["derived"]) == DERIVED_KEYS
    assert "source_categories" in result["fields"]  # system fields are part of fields


def test_document_item_text_links_and_scope(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session, name_en="Linked project", in_paper_scope=True, scope_note="In scope."
        ).entity_id
        document = create_document(session, "Example title", text="Повний текст документа.")
        apply_change(
            session,
            "document",
            document.entity_id,
            {"links": [{"subject_id": project, "state": "confirmed"}]},
            USER,
        )
        detail = item(session, "document", document.entity_id)
        listed = list_entities(session, "document", {})["items"][0]
        without_text = create_document(session, "No text")
        empty_detail = item(session, "document", without_text.entity_id)
    assert detail["label"] == "Example title"
    assert detail["fields"]["text"] == "Повний текст документа."
    assert "text" not in listed["fields"]
    assert empty_detail["fields"]["text"] is None
    assert detail["fields"]["links"][0]["subject_id"] == project
    assert detail["fields"]["links"][0]["origin"] == "manual"
    assert detail["refs"][f"links.{project}"]["label"] == "Linked project"
    assert detail["virtual"]["linked_in_paper_scope"] is True
    assert "derived" not in detail


def test_event_item(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Event subject").entity_id
        dated = create_event(session, project, "launch", "2012-05").entity_id
        undated = create_event(session, project, "announced").entity_id
        dated_item = item(session, "event", dated)
        assert label(session, "event", undated) == "Example announced · Event subject · undated"
    assert dated_item["label"] == "Example launch · Event subject · 2012-05"
    assert dated_item["fields"]["date"] == "2012-05"
    assert dated_item["refs"]["subject_id"]["label"] == "Event subject"
    assert dated_item["virtual"]["subject_in_paper_scope"] is False
    assert "derived" not in dated_item


def test_label_rules_of_the_other_types(db: Db) -> None:
    with db.session() as session:
        focal = focal_org_id(session)
        alpha = create_project(session, name_en="Alpha").entity_id
        beta = create_project(session, name_en=None, name_uk="Бета").entity_id
        participation = create(
            session, "participation", organization_id=focal, subject_id=alpha, role="initiator"
        ).entity_id
        relation = create(
            session, "relation", from_id=alpha, to_id=beta, relation_type="relates_a"
        ).entity_id
        with_unit = create(
            session, "indicator", subject_id=alpha, metric="Users", value=15.0, unit="people"
        ).entity_id
        without_unit = create(
            session, "indicator", subject_id=beta, metric="Share", value=0.5
        ).entity_id
        evidence = create_evidence(session, alpha, "name_en").entity_id
        component = create(session, "component", name_en=None, name_uk="Компонент").entity_id
        view = apply_change(
            session,
            "saved_view",
            None,
            {"name": "My view", "entity_type": "project", "query": "sort=name_en"},
            USER,
        ).entity_id
        assert label(session, "participation", participation) == (
            "Example focal organisation · Example initiator · Alpha"
        )
        assert label(session, "relation", relation) == "Alpha Example relates_a Бета"
        assert label(session, "indicator", with_unit) == "Users: 15 people"
        assert label(session, "indicator", without_unit) == "Share: 0.5"
        assert label(session, "evidence", evidence) == "field:name_en · Alpha"
        assert label(session, "component", component) == "Компонент"
        assert label(session, "saved_view", view) == "My view"
        assert label(session, "organization", focal) == "Example focal organisation"
        terms = list_entities(
            session, "vocabulary_term", {"f.vocabulary": "eq:status", "f.code": "eq:active"}
        )
        assert terms["items"][0]["label"] == "status:active"
        assert terms["items"][0]["fields"]["attributes"] == {}


def test_derived_refs(db: Db) -> None:
    with db.session() as session:
        focal = focal_org_id(session)
        project = create_project(session, name_en="Derived refs").entity_id
        launch = create_event(session, project, "launch", "2012-05").entity_id
        archived = create_event(session, project, "first_archived", "2012-08-01").entity_id
        change = create_event(session, project, "expansion", "2017-01").entity_id
        participation = create(
            session,
            "participation",
            organization_id=focal,
            subject_id=project,
            role="owner",
            start="2013",
        ).entity_id
        result = item(session, "project", project)
    derived = result["derived"]
    assert (derived["war_trajectory"], derived["trajectory_event_id"]) == ("adapted_in_war", change)
    assert derived["portfolio_entry"] == "2013"
    assert derived["portfolio_entry_start"] == "2013-01-01"
    assert derived["portfolio_entry_precision"] == "year"
    refs = result["refs"]
    assert refs["derived.launch_event_id"]["id"] == launch
    assert refs["derived.existed_by_event_id"]["id"] == archived
    assert refs["derived.trajectory_event_id"]["id"] == change
    assert refs["derived.portfolio_entry_participation_id"]["id"] == participation
    assert refs["derived.portfolio_entry_participation_id"]["type"] == "participation"


def test_deleted_items_and_deleted_refs(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Soon deleted").entity_id
        event = create_event(session, project, "announced").entity_id
        soft_delete(session, "project", project, USER)
        deleted = item(session, "project", project)
        event_item = item(session, "event", event)
    assert deleted["deleted_at"] is not None
    assert deleted["deleted_by"] == USER.name
    assert deleted["version"] == 2
    assert event_item["refs"]["subject_id"]["deleted"] is True


def test_get_item_errors(db: Db) -> None:
    with db.session() as session:
        project = create_project(session).entity_id
        with pytest.raises(NotFoundError):
            item(session, "project", "prj_01J00000000000000000000000")
        with pytest.raises(NotFoundError):
            item(session, "service", project)
        with pytest.raises(NotFoundError):
            item(session, "unknown", project)
        with pytest.raises(NotFoundError):
            item(session, "comment", project)


# --------------------------------------------------------------------------------------
# Comment counts on items
# --------------------------------------------------------------------------------------


def test_comment_counts_and_open_comments_by_field(db: Db) -> None:
    with db.session() as session:
        project = create_project(session).entity_id
        create_comment(session, project, "On the English name", USER, field="name_en")
        create_comment(session, project, "Also on the name", USER, field="name_en")
        create_comment(session, project, "On the launch", USER, field="launch")
        root = create_comment(session, project, "Entity-level", USER)
        create_comment(session, project, "A reply", USER, parent_id=root.entity_id)
        resolved = create_comment(session, project, "Resolved", USER, field="status")
        resolve_comment(session, resolved.entity_id, USER)
        hidden = create_comment(session, project, "Deleted thread", USER)
        create_comment(
            session, project, "Reply in a deleted thread", USER, parent_id=hidden.entity_id
        )
        delete_comment(session, hidden.entity_id, USER)
        reply = create_comment(session, project, "Deleted reply", USER, parent_id=root.entity_id)
        delete_comment(session, reply.entity_id, USER)
        result = item(session, "project", project)
    assert result["virtual"]["open_comments"] == 4
    # visible comments: 5 roots and replies minus the deleted thread and the deleted reply
    assert result["virtual"]["comment_count"] == 6
    assert result["virtual"]["open_comments_by_field"] == {"name_en": 2, "launch": 1, "": 1}


# --------------------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------------------


def test_comment_representation(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Commented project").entity_id
        root = create_comment(
            session,
            project,
            "See [source](https://example.org/a) <script>alert(1)</script> **bold**",
            USER,
            field="name_en",
        )
        reply = create_comment(session, project, "Reply", USER, parent_id=root.entity_id)
        edit_comment(session, root.entity_id, "Edited **body**", USER)
        root_comment = get_comment(session, root.entity_id)
        reply_comment = get_comment(session, reply.entity_id)
        with pytest.raises(NotFoundError):
            get_comment(session, "cmt_01J00000000000000000000000")
    assert set(root_comment) == COMMENT_KEYS
    assert root_comment["subject_type"] == "project"
    assert root_comment["subject_label"] == "Commented project"
    assert root_comment["field"] == "name_en"
    assert root_comment["status"] == "open"
    assert root_comment["edited"] is True
    assert root_comment["body_html"] == "<p>Edited <strong>body</strong></p>\n"
    assert reply_comment["status"] is None
    assert reply_comment["parent_id"] == root.entity_id
    assert reply_comment["field"] == "name_en"  # replies take their root's field
    assert reply_comment["edited"] is False


def test_comment_body_html_is_rendered_markdown(db: Db) -> None:
    with db.session() as session:
        project = create_project(session).entity_id
        comment = create_comment(
            session,
            project,
            "[x](javascript:alert(1)) <img src=x onerror=1> [ok](https://example.org)",
            USER,
        )
        html = get_comment(session, comment.entity_id)["body_html"]
    assert 'href="javascript' not in html  # the refused link stays plain text
    assert "<img" not in html
    assert '<a href="https://example.org">ok</a>' in html


# --------------------------------------------------------------------------------------
# Reference IDs in revisions
# --------------------------------------------------------------------------------------


def test_reference_ids_in_fields_and_diffs() -> None:
    fields = {
        "project_id": "prj_A",
        "parent_service_id": None,
        "name_en": "prj_not_a_ref",
        "unknown_field": "prj_B",
    }
    assert field_ref_ids(SERVICE, fields) == ["prj_A"]
    document = ENTITY_TYPES["document"]
    links = [{"subject_id": "prj_C", "state": "confirmed"}, {"state": "broken"}]
    assert field_ref_ids(document, {"links": links}) == ["prj_C"]
    diff = {"fields": {"project_id": ["prj_A", "prj_D"], "name_en": ["a", "b"], "bad": "x"}}
    assert sorted(diff_ref_ids(SERVICE, diff)) == ["prj_A", "prj_D"]
    assert diff_ref_ids(SERVICE, None) == []
