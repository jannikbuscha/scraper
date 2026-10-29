"""Feeds and histories (docs/API.md §3.2-§3.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from mdt.domain.comments import (
    create_comment,
    delete_comment,
    edit_comment,
    resolve_comment,
)
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.feeds import (
    comments_listing,
    entity_diff,
    entity_revision,
    entity_revisions,
    recent_changes,
    revision_by_id,
)
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import USER, create_project, create_service, revisions_of
from tests.read_helpers import term_id, update

FEED_KEYS = {
    "id",
    "entity_type",
    "entity_id",
    "entity_label",
    "version",
    "at",
    "author",
    "channel",
    "action",
    "note",
    "changed_fields",
    "restored_from_version",
    "batch_id",
    "context",
}


# --------------------------------------------------------------------------------------
# Recent changes
# --------------------------------------------------------------------------------------


@pytest.fixture
def history(db: Db) -> dict[str, Any]:
    """A small history: create, update, comment, resolve, term edit, saved view, delete."""
    with db.session() as session:
        project = create_project(session, name_en="Feed project").entity_id
        update(session, "project", project, USER, notes="Checked")
        comment = create_comment(session, project, "Feed comment", USER, field="name_en")
        reply = create_comment(session, project, "Feed reply", USER, parent_id=comment.entity_id)
        resolve_comment(session, comment.entity_id, USER)
        term = term_id(session, "status", "active")
        update(session, "vocabulary_term", term, USER, definition="Edited definition.")
        view = apply_change(
            session,
            "saved_view",
            None,
            {"name": "Feed view", "entity_type": "project", "query": "sort=name_en"},
            USER,
        ).entity_id
        deleted = soft_delete(session, "project", project, USER)
        return {
            "project": project,
            "comment": comment.entity_id,
            "reply": reply.entity_id,
            "term": term,
            "view": view,
            "batch": deleted.batch_id,
        }


def feed(db: Db, **params: str) -> dict[str, Any]:
    with db.session() as session:
        return recent_changes(session, params)


def test_recent_changes_newest_first_with_labels_and_changed_fields(
    db: Db, history: dict[str, Any]
) -> None:
    result = feed(db, page_size="7")
    items = result["items"]
    assert [item["id"] for item in items] == sorted((item["id"] for item in items), reverse=True)
    assert set(items[0]) == FEED_KEYS
    newest = items[0]
    assert (newest["entity_id"], newest["action"], newest["author"]) == (
        history["project"],
        "delete",
        USER.name,
    )
    assert newest["entity_label"] == "Feed project"  # deleted rows keep their label
    assert newest["changed_fields"] == ["deleted"]
    assert newest["context"] is None
    assert result["total"] > 7
    assert (result["page"], result["page_size"]) == (1, 7)


def test_recent_changes_filters(db: Db, history: dict[str, Any]) -> None:
    ui = feed(db, channel="ui", page_size="500")
    assert ui["total"] == 8
    assert {item["author"] for item in ui["items"]} == {"user"}
    project_history = feed(db, entity_id=history["project"])["items"]
    assert [item["action"] for item in project_history] == ["delete", "update", "create"]
    assert project_history[1]["changed_fields"] == ["notes"]
    assert [item["action"] for item in feed(db, action="delete")["items"]] == ["delete"]
    assert [item["entity_id"] for item in feed(db, batch_id=history["batch"])["items"]] == [
        history["project"]
    ]
    seeded = feed(db, channel="seed", page_size="500")
    assert seeded["total"] > 0
    assert {item["channel"] for item in seeded["items"]} == {"seed"}
    assert feed(db, channel="ui,seed")["total"] == seeded["total"] + 8


def test_recent_changes_contexts(db: Db, history: dict[str, Any]) -> None:
    comments = feed(db, entity_type="comment")["items"]
    assert [item["action"] for item in comments] == ["resolve", "create", "create"]
    reply = next(item for item in comments if item["entity_id"] == history["reply"])
    assert reply["context"] == {
        "subject_id": history["project"],
        "subject_type": "project",
        "field": "name_en",
        "parent_id": history["comment"],
    }
    assert reply["entity_label"] == "Comment on Feed project · Name (English)"
    root = next(item for item in comments if item["entity_id"] == history["comment"])
    assert root["context"]["parent_id"] is None
    terms = feed(db, entity_type="vocabulary_term", channel="ui")["items"]
    assert [(item["entity_id"], item["context"]) for item in terms] == [
        (history["term"], {"vocabulary": "status"})
    ]
    views = feed(db, entity_type="saved_view")["items"]
    assert views[0]["context"] == {"entity_type": "project"}
    assert views[0]["entity_label"] == "Feed view"


def test_recent_changes_time_bounds_are_inclusive(db: Db, history: dict[str, Any]) -> None:
    with db.session() as session:
        update_revision = revisions_of(session, history["project"])[1]
    at = update_revision.at
    since = feed(db, since=at, page_size="500")["items"]
    assert since[-1]["id"] == update_revision.id
    until = feed(db, until=at, entity_id=history["project"])["items"]
    assert [item["version"] for item in until] == [2, 1]
    # the same instant written with an offset
    instant = datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    shifted = instant.astimezone(timezone(timedelta(hours=2))).isoformat()
    assert feed(db, since=shifted, page_size="500")["items"][-1]["id"] == update_revision.id
    today = date.fromisoformat(at[:10])
    assert feed(db, since=today.isoformat())["total"] == feed(db)["total"]
    assert feed(db, until=(today - timedelta(days=1)).isoformat())["total"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"since": "yesterday"},
        {"until": "2026-02-30"},
        {"since": "2026-10-28T10:00:00"},  # no time zone
        {"channel": "web"},
        {"action": "edit"},
        {"entity_type": "unknown"},
        {"page_size": "501"},
    ],
)
def test_recent_changes_rejects_invalid_parameters(db: Db, params: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        feed(db, **params)


@pytest.mark.parametrize(
    ("params", "everything"),
    [
        ({"until": "0001-01-01T00:00:00Z"}, False),
        ({"since": "0999-01-01T00:00:00+00:30"}, True),
        ({"since": "0100-06-01T12:00:00+00:00"}, True),
        ({"until": "9999-12-31T22:59:59+01:00"}, True),
    ],
)
def test_recent_changes_accepts_early_and_late_years(
    db: Db, history: dict[str, Any], params: dict[str, str], everything: bool
) -> None:
    # Years before 1000 used to produce "999-…" bounds that the timestamp column refused.
    expected = feed(db)["total"] if everything else 0
    assert feed(db, **params)["total"] == expected


# --------------------------------------------------------------------------------------
# Comment threads of one subject
# --------------------------------------------------------------------------------------


@pytest.fixture
def threads(db: Db) -> dict[str, str]:
    with db.session() as session:
        subject = create_project(session, name_en="Thread subject").entity_id
        ids = {"subject": subject}
        ids["root1"] = create_comment(session, subject, "Root one", USER, field="name_en").entity_id
        ids["root2"] = create_comment(session, subject, "Root two", USER).entity_id
        ids["r1"] = create_comment(
            session, subject, "Reply 1", USER, parent_id=ids["root1"]
        ).entity_id
        ids["r2"] = create_comment(
            session, subject, "Reply 2", USER, parent_id=ids["root1"]
        ).entity_id
        ids["root3"] = create_comment(
            session, subject, "Root three", USER, field="status"
        ).entity_id
        resolve_comment(session, ids["root3"], USER)
        ids["root4"] = create_comment(session, subject, "Root four", USER).entity_id
        ids["r3"] = create_comment(
            session, subject, "Reply 3", USER, parent_id=ids["root4"]
        ).entity_id
        delete_comment(session, ids["root4"], USER)
        ids["r4"] = create_comment(
            session, subject, "Reply 4", USER, parent_id=ids["root2"]
        ).entity_id
        delete_comment(session, ids["r4"], USER)
        return ids


def thread_ids(db: Db, ids: dict[str, str], **params: str) -> list[tuple[str, list[str]]]:
    names = {value: key for key, value in ids.items()}
    with db.session() as session:
        result = comments_listing(session, {"subject_id": ids["subject"], **params})
    return [
        (names[thread["root"]["id"]], [names[reply["id"]] for reply in thread["replies"]])
        for thread in result["threads"]
    ]


def test_threads_newest_root_first_replies_oldest_first(db: Db, threads: dict[str, str]) -> None:
    assert thread_ids(db, threads) == [("root3", []), ("root2", []), ("root1", ["r1", "r2"])]
    assert thread_ids(db, threads, status="all") == thread_ids(db, threads)


def test_threads_filter_by_status_and_field(db: Db, threads: dict[str, str]) -> None:
    assert thread_ids(db, threads, status="open") == [("root2", []), ("root1", ["r1", "r2"])]
    assert thread_ids(db, threads, status="resolved") == [("root3", [])]
    assert thread_ids(db, threads, field="name_en") == [("root1", ["r1", "r2"])]
    assert thread_ids(db, threads, field="-") == [("root2", [])]
    with pytest.raises(ValidationError):
        thread_ids(db, threads, status="closed")


def test_threads_deleted_modes(db: Db, threads: dict[str, str]) -> None:
    assert thread_ids(db, threads, deleted="include") == [
        ("root4", ["r3"]),
        ("root3", []),
        ("root2", ["r4"]),
        ("root1", ["r1", "r2"]),
    ]
    assert thread_ids(db, threads, deleted="only") == [("root4", ["r3"])]


def test_thread_comments_are_full_comment_objects(db: Db, threads: dict[str, str]) -> None:
    with db.session() as session:
        result = comments_listing(session, {"subject_id": threads["subject"], "field": "name_en"})
    root = result["threads"][0]["root"]
    assert root["body_html"] == "<p>Root one</p>\n"
    assert root["subject_label"] == "Thread subject"
    assert result["threads"][0]["replies"][0]["status"] is None


def test_threads_of_a_subject_without_comments(db: Db) -> None:
    with db.session() as session:
        assert comments_listing(session, {"subject_id": "prj_01J00000000000000000000000"}) == {
            "threads": []
        }


# --------------------------------------------------------------------------------------
# Comment feed
# --------------------------------------------------------------------------------------


@pytest.fixture
def comment_feed(db: Db) -> dict[str, str]:
    with db.session() as session:
        project = create_project(session, name_en="Feed subject").entity_id
        service = create_service(session, project, name_en="Feed service").entity_id
        term = term_id(session, "status", "planned")
        ids = {"project": project}
        ids["A"] = create_comment(session, project, "Check the launch date", USER).entity_id
        ids["B"] = create_comment(session, service, "Typo in the name", USER).entity_id
        ids["C"] = create_comment(session, term, "Definition unclear", USER).entity_id
        ids["reply"] = create_comment(
            session, project, "I found the source document", USER, parent_id=ids["A"]
        ).entity_id
        ids["D"] = create_comment(session, project, "Obsolete remark", USER).entity_id
        delete_comment(session, ids["D"], USER)
        resolve_comment(session, ids["B"], USER)
        return ids


def feed_roots(db: Db, ids: dict[str, str], **params: str) -> list[str]:
    names = {value: key for key, value in ids.items()}
    with db.session() as session:
        result = comments_listing(session, params)
    return [names[item["root"]["id"]] for item in result["items"]]


def test_comment_feed_orders_threads_by_last_activity(db: Db, comment_feed: dict[str, str]) -> None:
    assert feed_roots(db, comment_feed) == ["B", "A", "C"]
    with db.session() as session:
        result = comments_listing(session, {})
        reply = comments_listing(session, {"subject_id": comment_feed["project"]})
    items = {item["root"]["id"]: item for item in result["items"]}
    thread_a = items[comment_feed["A"]]
    assert thread_a["reply_count"] == 1
    reply_comment = reply["threads"][0]["replies"][0]
    assert thread_a["last_activity_at"] == reply_comment["updated_at"]
    assert (
        items[comment_feed["C"]]["last_activity_at"]
        == items[comment_feed["C"]]["root"]["updated_at"]
    )
    assert (result["total"], result["page"], result["page_size"]) == (3, 1, 50)


def test_comment_feed_filters(db: Db, comment_feed: dict[str, str]) -> None:
    assert feed_roots(db, comment_feed, status="open") == ["A", "C"]
    assert feed_roots(db, comment_feed, status="resolved") == ["B"]
    assert feed_roots(db, comment_feed, entity_type="project") == ["A"]
    assert feed_roots(db, comment_feed, entity_type="service,vocabulary_term") == ["B", "C"]
    assert feed_roots(db, comment_feed, q="source") == ["A"]  # matches the reply
    assert feed_roots(db, comment_feed, q="TYPO") == ["B"]
    assert feed_roots(db, comment_feed, q="- .") == []
    assert feed_roots(db, comment_feed, deleted="only") == ["D"]
    assert feed_roots(db, comment_feed, deleted="include") == ["B", "D", "A", "C"]
    with pytest.raises(ValidationError):
        feed_roots(db, comment_feed, entity_type="comment")


def test_comment_trash_lists_the_newest_deletion_first(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, name_en="Trash subject").entity_id
        early = create_comment(session, project, "Deleted first", USER).entity_id
        reply = create_comment(session, project, "A reply", USER, parent_id=early).entity_id
        late = create_comment(session, project, "Deleted second", USER).entity_id
        delete_comment(session, early, USER)
        delete_comment(session, late, USER)
        # Activity in the earlier deleted thread after the second deletion.
        edit_comment(session, reply, "An edited reply", USER)
    ids = {"early": early, "late": late}
    # By deletion time, not by last activity (which would put "early" first).
    assert feed_roots(db, ids, deleted="only") == ["late", "early"]
    assert feed_roots(db, ids, deleted="include") == ["early", "late"]


def test_comment_feed_paging(db: Db, comment_feed: dict[str, str]) -> None:
    with db.session() as session:
        page = comments_listing(session, {"page": "2", "page_size": "2"})
    assert page["total"] == 3
    assert [item["root"]["id"] for item in page["items"]] == [comment_feed["C"]]


# --------------------------------------------------------------------------------------
# Revisions of one record
# --------------------------------------------------------------------------------------


@pytest.fixture
def moved_service(db: Db) -> dict[str, str]:
    with db.session() as session:
        first = create_project(session, name_en="First project").entity_id
        second = create_project(session, name_en="Second project").entity_id
        service = create_service(session, first, name_en="Moved service").entity_id
        update(session, "service", service, USER, project_id=second)
        comment = create_comment(session, service, "Before", USER).entity_id
        edit_comment(session, comment, "After", USER)
        return {"first": first, "second": second, "service": service, "comment": comment}


def test_entity_revisions_newest_first_with_refs(db: Db, moved_service: dict[str, str]) -> None:
    with db.session() as session:
        result = entity_revisions(session, "service", moved_service["service"], {})
        second_page = entity_revisions(
            session, "service", moved_service["service"], {"page": "2", "page_size": "1"}
        )
    assert [item["version"] for item in result["items"]] == [2, 1]
    assert [item["action"] for item in result["items"]] == ["update", "create"]
    assert result["items"][0]["changed_fields"] == ["project_id"]
    assert result["items"][0]["restored_from_version"] is None
    assert result["total"] == 2
    assert result["refs"][moved_service["first"]]["label"] == "First project"
    assert result["refs"][moved_service["second"]]["label"] == "Second project"
    assert [item["version"] for item in second_page["items"]] == [1]


def test_entity_revisions_of_comments_and_errors(db: Db, moved_service: dict[str, str]) -> None:
    with db.session() as session:
        comments = entity_revisions(session, "comment", moved_service["comment"], {})
        assert [item["changed_fields"] for item in comments["items"]] == [
            ["body_md"],
            ["body_md", "status"],
        ]
        with pytest.raises(NotFoundError):
            entity_revisions(session, "project", moved_service["service"], {})
        with pytest.raises(NotFoundError):
            entity_revisions(session, "unknown", moved_service["service"], {})


def test_entity_revision_and_diff(db: Db, moved_service: dict[str, str]) -> None:
    service = moved_service["service"]
    with db.session() as session:
        first = entity_revision(session, "service", service, 1)
        diff = entity_diff(session, "service", service, 0, 2)
        with pytest.raises(NotFoundError):
            entity_revision(session, "service", service, 9)
        with pytest.raises(ValidationError):
            entity_diff(session, "service", service, 2, 1)
    revision = first["revision"]
    assert revision["version"] == 1
    assert revision["snapshot"]["fields"]["project_id"] == moved_service["first"]
    assert revision["diff"]["fields"]["name_en"] == [None, "Moved service"]
    assert "schema_revision" in revision
    assert first["refs"][moved_service["first"]]["label"] == "First project"
    assert diff["diff"]["fields"]["project_id"] == [None, moved_service["second"]]
    assert (diff["from"], diff["to"], diff["not_recorded"]) == (0, 2, [])
    assert list(diff["refs"]) == [moved_service["second"]]


def test_revision_by_id(db: Db, moved_service: dict[str, str]) -> None:
    with db.session() as session:
        service_revision = revisions_of(session, moved_service["service"])[1]
        comment_revision = revisions_of(session, moved_service["comment"])[0]
        result = revision_by_id(session, service_revision.id)
        comment = revision_by_id(session, comment_revision.id)
        with pytest.raises(NotFoundError):
            revision_by_id(session, 10**9)
    assert (result["entity_type"], result["entity_id"]) == ("service", moved_service["service"])
    assert result["entity_label"] == "Moved service"
    assert result["revision"]["diff"]["fields"]["project_id"] == [
        moved_service["first"],
        moved_service["second"],
    ]
    assert set(result["refs"]) == {moved_service["first"], moved_service["second"]}
    assert comment["entity_type"] == "comment"
    assert comment["entity_label"] == "Comment on Moved service"
