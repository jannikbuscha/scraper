"""Comments: threads, status, revisions and Markdown (DATA_MODEL §6.6, API §3.3)."""

from __future__ import annotations

import pytest

from mdt.domain.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    edited_comment_ids,
    render_markdown,
    reopen_comment,
    resolve_comment,
    restore_comment,
    undelete_comment,
)
from mdt.domain.errors import EntityDeletedError, ValidationError
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import (
    USER,
    assert_matches_latest_snapshot,
    create_project,
    load,
    revisions_of,
)


def test_root_comment(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        result = create_comment(session, project_id, "  First **remark**  ", USER, field="name_en")
        row = load(session, "comment", result.entity_id)
        assert result.entity_id.startswith("cmt_")
        assert (row["subject_id"], row["field"], row["parent_id"], row["status"]) == (
            project_id,
            "name_en",
            None,
            "open",
        )
        assert row["body_md"] == "First **remark**"
        assert (row["version"], row["created_by"]) == (1, USER.by)
        [revision] = revisions_of(session, result.entity_id)
        assert (revision.entity_type, revision.action, revision.channel) == (
            "comment",
            "create",
            "ui",
        )
        assert revision.diff == {
            "fields": {"body_md": [None, "First **remark**"], "status": [None, "open"]}
        }
        assert revision.snapshot["field_meta"] == {}
        assert revision.snapshot["state"] == {"deleted_at": None, "deleted_by": None}
    assert_matches_latest_snapshot(db, "comment", result.entity_id)


def test_replies(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        other_id = create_project(session).entity_id
        root = create_comment(session, project_id, "Root", USER, field="slug").entity_id
        reply = create_comment(session, project_id, "Reply", USER, parent_id=root).entity_id
        row = load(session, "comment", reply)
        assert (row["status"], row["field"], row["parent_id"]) == (None, "slug", root)
        assert load(session, "comment", root)["status"] == "open"
        # The reply may repeat the root's field.
        create_comment(session, project_id, "Reply 2", USER, parent_id=root, field="slug")
        cases = [
            ({"parent_id": reply}, "parent_id", "Replies must answer a root comment"),
            (
                {"parent_id": root, "subject_id": other_id},
                "parent_id",
                "The root comment belongs to another subject",
            ),
            (
                {"parent_id": root, "field": "name_en"},
                "field",
                "A reply belongs to the field of its root comment",
            ),
            (
                {"parent_id": "cmt_01JBX3ABCDEFGHJKMNPQRSTVWX"},
                "parent_id",
                "refers to a comment that does not exist",
            ),
        ]
        for overrides, path, message in cases:
            data = {"subject_id": project_id, "body_md": "Invalid reply", **overrides}
            with pytest.raises(ValidationError) as caught:
                apply_change(session, "comment", None, data, USER)
            assert caught.value.details == {path: [message]}
        delete_comment(session, root, USER)
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "Too late", USER, parent_id=root)
        assert caught.value.details == {"parent_id": ["A deleted thread cannot be answered"]}


def test_subjects_and_fields(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        create_comment(session, project_id, "On a derived field", USER, field="launch")
        create_comment(session, project_id, "On a system column", USER, field="updated_at")
        root = create_comment(session, project_id, "Root", USER).entity_id
        for subject, field, path in (
            (project_id, "unicorn", "field"),
            (project_id, "seed_key", "field"),
            (root, None, "subject_id"),
            ("prj_01JBX3ABCDEFGHJKMNPQRSTVWX", None, "subject_id"),
            ("not-an-id", None, "subject_id"),
        ):
            with pytest.raises(ValidationError) as caught:
                create_comment(session, subject, "Body", USER, field=field)
            assert path in (caught.value.details or {})
        # Deleted subjects can still be discussed.
        soft_delete(session, "project", project_id, USER)
        assert create_comment(session, project_id, "After deletion", USER).changed


def test_body_rules(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "   ", USER)
        assert caught.value.details == {"body_md": ["is required"]}
        limit = db.settings.max_comment_chars
        assert create_comment(session, project_id, "b" * limit, USER).changed
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "b" * (limit + 1), USER)
        assert caught.value.details == {"body_md": [f"must be at most {limit} characters"]}
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "comment",
                None,
                {"subject_id": project_id, "body_md": "x", "status": "resolved"},
                USER,
            )
        assert caught.value.details == {"status": ["is set by the system"]}


def test_edit_and_edited_flag(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        comment_id = create_comment(session, project_id, "Original", USER).entity_id
        other_id = create_comment(session, project_id, "Untouched", USER).entity_id
        resolve_comment(session, other_id, USER)
        assert edited_comment_ids(session, [comment_id, other_id]) == set()
        result = edit_comment(session, comment_id, "Edited", USER, note="Typo")
        assert result.version == 2
        assert edited_comment_ids(session, [comment_id, other_id]) == {comment_id}
        assert edited_comment_ids(session, []) == set()
        revision = revisions_of(session, comment_id)[-1]
        assert (revision.action, revision.note, revision.diff) == (
            "update",
            "Typo",
            {"fields": {"body_md": ["Original", "Edited"]}},
        )
        no_op = edit_comment(session, comment_id, " Edited ", USER)
        assert not no_op.changed
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "comment",
                comment_id,
                {"field": "slug"},
                USER,
            )
    assert_matches_latest_snapshot(db, "comment", comment_id)


def test_resolve_and_reopen_are_idempotent(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        root = create_comment(session, project_id, "Root", USER).entity_id
        reply = create_comment(session, project_id, "Reply", USER, parent_id=root).entity_id
        result = resolve_comment(session, root, USER)
        assert result.changed and result.version == 2
        row = load(session, "comment", root)
        assert (row["status"], row["resolved_by"], row["resolved_at"]) == (
            "resolved",
            USER.by,
            row["updated_at"],
        )
        assert revisions_of(session, root)[-1].action == "resolve"
        # Already resolved: no revision.
        again = resolve_comment(session, root, USER)
        assert (again.changed, again.version, again.revision_id) == (False, 2, None)
        reopened = reopen_comment(session, root, USER)
        assert reopened.changed
        row = load(session, "comment", root)
        assert (row["status"], row["resolved_by"], row["resolved_at"]) == ("open", None, None)
        assert revisions_of(session, root)[-1].action == "reopen"
        assert not reopen_comment(session, root, USER).changed
        # Replies have no status.
        with pytest.raises(ValidationError):
            resolve_comment(session, reply, USER)
    assert_matches_latest_snapshot(db, "comment", root)


def test_deleting_a_root_hides_the_thread_without_touching_replies(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        root = create_comment(session, project_id, "Root", USER).entity_id
        reply = create_comment(session, project_id, "Reply", USER, parent_id=root).entity_id
        deleted = delete_comment(session, root, USER, note="Off topic")
        assert deleted.version == 2
        assert load(session, "comment", root)["deleted_by"] == USER.by
        assert load(session, "comment", reply)["deleted_at"] is None
        assert load(session, "comment", reply)["version"] == 1
        revision = revisions_of(session, root)[-1]
        assert revision.action == "delete" and set(revision.diff) == {"state"}
        with pytest.raises(EntityDeletedError):
            edit_comment(session, root, "Changed", USER)
        with pytest.raises(EntityDeletedError):
            resolve_comment(session, root, USER)
        undelete_comment(session, root, USER)
        assert load(session, "comment", root)["deleted_at"] is None
        edit_comment(session, root, "Root edited", USER)
        restore_comment(session, root, 1, USER)
        assert load(session, "comment", root)["body_md"] == "Root"
    assert_matches_latest_snapshot(db, "comment", root)


# --------------------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------------------


def test_markdown_features() -> None:
    html = render_markdown(
        "# Title\n\n**bold** *em* ~~gone~~ `code`\n\n> quote\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n1. one\n2. two\n"
    )
    for tag in ("<h1>", "<strong>", "<em>", "<s>", "<code>", "<blockquote>", "<table>", "<ol>"):
        assert tag in html
    linked = render_markdown("See https://example.org/page and [docs](https://example.org/docs).")
    assert '<a href="https://example.org/page">' in linked
    assert '<a href="https://example.org/docs">' in linked
    assert 'href="mailto:someone@example.org"' in render_markdown("[m](mailto:someone@example.org)")


def test_raw_html_is_shown_as_text() -> None:
    html = render_markdown("<script>alert(1)</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html
