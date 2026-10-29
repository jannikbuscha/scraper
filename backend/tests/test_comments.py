"""Comments: threads, status, revisions and sanitised Markdown (DATA_MODEL §6.6, API §3.3)."""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser

import pytest
from markdown_it import MarkdownIt

from mdt.db.session import read_transaction
from mdt.domain import comments
from mdt.domain.comments import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_TAGS,
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
from mdt.domain.errors import ConflictError, EntityDeletedError, ValidationError
from mdt.domain.feeds import comments_listing
from mdt.domain.registry import COMMENT
from mdt.domain.revisions import apply_change, soft_delete
from mdt.domain.serialize import load_rows, serialize_comments
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_project,
    load,
    revisions_of,
)


def test_root_comment(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        result = create_comment(session, project_id, "  First **remark**  ", ALICE, field="name_en")
        row = load(session, "comment", result.entity_id)
        assert result.entity_id.startswith("cmt_")
        assert (row["subject_id"], row["field"], row["parent_id"], row["status"]) == (
            project_id,
            "name_en",
            None,
            "open",
        )
        assert row["body_md"] == "First **remark**"
        assert (row["version"], row["created_by"]) == (1, ALICE.by)
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
        root = create_comment(session, project_id, "Root", ALICE, field="slug").entity_id
        reply = create_comment(session, project_id, "Reply", BOB, parent_id=root).entity_id
        row = load(session, "comment", reply)
        assert (row["status"], row["field"], row["parent_id"]) == (None, "slug", root)
        assert load(session, "comment", root)["status"] == "open"
        # The reply may repeat the root's field.
        create_comment(session, project_id, "Reply 2", BOB, parent_id=root, field="slug")
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
                apply_change(session, "comment", None, data, BOB)
            assert caught.value.details == {path: [message]}
        delete_comment(session, root, ALICE, expected_version=1)
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "Too late", BOB, parent_id=root)
        assert caught.value.details == {"parent_id": ["A deleted thread cannot be answered"]}


def test_subjects_and_fields(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        create_comment(session, project_id, "On a derived field", ALICE, field="launch")
        create_comment(session, project_id, "On a system column", ALICE, field="updated_at")
        root = create_comment(session, project_id, "Root", ALICE).entity_id
        for subject, field, path in (
            (project_id, "unicorn", "field"),
            (project_id, "seed_key", "field"),
            (root, None, "subject_id"),
            ("prj_01JBX3ABCDEFGHJKMNPQRSTVWX", None, "subject_id"),
            ("not-an-id", None, "subject_id"),
        ):
            with pytest.raises(ValidationError) as caught:
                create_comment(session, subject, "Body", ALICE, field=field)
            assert path in (caught.value.details or {})
        # Deleted subjects can still be discussed.
        soft_delete(session, "project", project_id, ALICE, expected_version=1)
        assert create_comment(session, project_id, "After deletion", ALICE).changed


def test_body_rules(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "   ", ALICE)
        assert caught.value.details == {"body_md": ["is required"]}
        limit = db.settings.max_comment_chars
        assert create_comment(session, project_id, "b" * limit, ALICE).changed
        with pytest.raises(ValidationError) as caught:
            create_comment(session, project_id, "b" * (limit + 1), ALICE)
        assert caught.value.details == {"body_md": [f"must be at most {limit} characters"]}
        with pytest.raises(ValidationError) as caught:
            apply_change(
                session,
                "comment",
                None,
                {"subject_id": project_id, "body_md": "x", "status": "resolved"},
                ALICE,
            )
        assert caught.value.details == {"status": ["is set by the system"]}


def test_edit_and_edited_flag(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        comment_id = create_comment(session, project_id, "Original", ALICE).entity_id
        other_id = create_comment(session, project_id, "Untouched", ALICE).entity_id
        resolve_comment(session, other_id, ALICE, expected_version=1)
        assert edited_comment_ids(session, [comment_id, other_id]) == set()
        result = edit_comment(session, comment_id, "Edited", BOB, note="Typo", expected_version=1)
        assert result.version == 2
        assert edited_comment_ids(session, [comment_id, other_id]) == {comment_id}
        assert edited_comment_ids(session, []) == set()
        revision = revisions_of(session, comment_id)[-1]
        assert (revision.action, revision.note, revision.diff) == (
            "update",
            "Typo",
            {"fields": {"body_md": ["Original", "Edited"]}},
        )
        no_op = edit_comment(session, comment_id, " Edited ", BOB, expected_version=2)
        assert not no_op.changed
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "comment",
                comment_id,
                {"field": "slug"},
                BOB,
                expected_version=2,
            )
    assert_matches_latest_snapshot(db, "comment", comment_id)


def test_resolve_and_reopen_are_idempotent(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        root = create_comment(session, project_id, "Root", ALICE).entity_id
        reply = create_comment(session, project_id, "Reply", ALICE, parent_id=root).entity_id
        result = resolve_comment(session, root, BOB, expected_version=1)
        assert result.changed and result.version == 2
        row = load(session, "comment", root)
        assert (row["status"], row["resolved_by"], row["resolved_at"]) == (
            "resolved",
            BOB.by,
            row["updated_at"],
        )
        assert revisions_of(session, root)[-1].action == "resolve"
        # Already resolved: no revision and no version check, even with a stale version.
        again = resolve_comment(session, root, ALICE, expected_version=1)
        assert (again.changed, again.version, again.revision_id) == (False, 2, None)
        reopened = reopen_comment(session, root, ALICE, expected_version=2)
        assert reopened.changed
        row = load(session, "comment", root)
        assert (row["status"], row["resolved_by"], row["resolved_at"]) == ("open", None, None)
        assert revisions_of(session, root)[-1].action == "reopen"
        assert not reopen_comment(session, root, ALICE, expected_version=1).changed
        # A real change with a stale version conflicts.
        with pytest.raises(ConflictError):
            resolve_comment(session, root, ALICE, expected_version=2)
        # Replies have no status.
        with pytest.raises(ValidationError):
            resolve_comment(session, reply, ALICE, expected_version=1)
        with pytest.raises(ValidationError):
            resolve_comment(session, root, ALICE)  # a real change needs expected_version
    assert_matches_latest_snapshot(db, "comment", root)


def test_deleting_a_root_hides_the_thread_without_touching_replies(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        root = create_comment(session, project_id, "Root", ALICE).entity_id
        reply = create_comment(session, project_id, "Reply", BOB, parent_id=root).entity_id
        deleted = delete_comment(session, root, ALICE, note="Off topic", expected_version=1)
        assert deleted.version == 2
        assert load(session, "comment", root)["deleted_by"] == ALICE.by
        assert load(session, "comment", reply)["deleted_at"] is None
        assert load(session, "comment", reply)["version"] == 1
        revision = revisions_of(session, root)[-1]
        assert revision.action == "delete" and set(revision.diff) == {"state"}
        with pytest.raises(EntityDeletedError):
            edit_comment(session, root, "Changed", ALICE, expected_version=2)
        with pytest.raises(EntityDeletedError):
            resolve_comment(session, root, ALICE, expected_version=2)
        undelete_comment(session, root, ALICE, expected_version=2)
        assert load(session, "comment", root)["deleted_at"] is None
        edit_comment(session, root, "Root edited", ALICE, expected_version=3)
        restore_comment(session, root, 1, ALICE, expected_version=4)
        assert load(session, "comment", root)["body_md"] == "Root"
    assert_matches_latest_snapshot(db, "comment", root)


# --------------------------------------------------------------------------------------
# Markdown rendering and sanitising
# --------------------------------------------------------------------------------------


def test_markdown_features() -> None:
    html = render_markdown(
        "# Title\n\n**bold** *em* ~~gone~~ `code`\n\n> quote\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n1. one\n2. two\n"
    )
    for tag in ("<h1>", "<strong>", "<em>", "<s>", "<code>", "<blockquote>", "<table>", "<ol>"):
        assert tag in html
    linked = render_markdown("See https://example.org/page and [docs](https://example.org/docs).")
    assert '<a href="https://example.org/page" rel="noopener noreferrer nofollow">' in linked
    assert '<a href="https://example.org/docs" rel="noopener noreferrer nofollow">' in linked
    assert 'href="mailto:someone@example.org"' in render_markdown("[m](mailto:someone@example.org)")


class _Elements(HTMLParser):
    """Collects the elements and attributes of rendered HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def _is_safe_href(href: str) -> bool:
    cleaned = re.sub(r"[\x00-\x20]", "", href).lower()
    if re.match(r"^(https?:|mailto:)", cleaned):
        return True
    return ":" not in cleaned.split("/", 1)[0] and not re.match(r"^/[/\\]", cleaned)


def assert_safe(html: str) -> None:
    """Only allowed elements and attributes, and only safe link targets."""
    parser = _Elements()
    parser.feed(html)
    parser.close()
    for tag, attrs in parser.found:
        assert tag in ALLOWED_TAGS, (tag, html)
        allowed = ALLOWED_ATTRIBUTES.get(tag, set()) | ({"rel"} if tag == "a" else set())
        assert set(attrs) <= allowed, (tag, attrs)
        href = attrs.get("href")
        if href is not None:
            assert _is_safe_href(href), href
        if tag == "a" and href is not None:
            assert attrs.get("rel") == "noopener noreferrer nofollow"


@pytest.mark.parametrize(
    "body",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">x</a>',
        "[click](javascript:alert(1))",
        "[click](JaVaScRiPt:alert(1))",
        "[click](java\tscript:alert(1))",
        "[click](vbscript:msgbox(1))",
        "[click](data:text/html;base64,PHNjcmlwdD4=)",
        "![x](javascript:alert(1))",
        "![x](https://example.org/image.png)",
        '<div onmouseover="alert(1)">x</div>',
        '<p style="background:url(javascript:alert(1))">x</p>',
        "<iframe src=https://example.org></iframe>",
        '[x](https://example.org "title" onclick=alert(1))',
        "<svg/onload=alert(1)>",
        "[a](//evil.example/x)",
        "[b](/\\evil.example/y)",
        "<https://example.org/autolink>",
        "javascript:alert(1)",
        "##### Heading five",
        '[titled](https://example.org "A title")',
    ],
)
def test_dangerous_markup_is_neutralised(body: str) -> None:
    assert_safe(render_markdown(body))


def test_raw_html_is_shown_as_text() -> None:
    html = render_markdown("<script>alert(1)</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_protocol_relative_and_backslash_links_are_dropped() -> None:
    html = render_markdown("[a](//evil.example/x) [b](/\\evil.example/y) [c](/local/page)")
    assert 'href="//' not in html
    assert 'href="/\\' not in html
    assert 'href="/local/page"' in html


def test_only_allowed_attributes_survive() -> None:
    html = render_markdown("| a |\n|:-:|\n| 1 |\n\n3. three\n4. four\n")
    assert 'align="center"' in html or "text-align" not in html
    assert '<ol start="3">' in html
    assert "class=" not in html and "id=" not in html


# --------------------------------------------------------------------------------------
# Rendering cost (crafted bodies) and the render cache
# --------------------------------------------------------------------------------------


def _upstream_markdown() -> MarkdownIt:
    """The renderer of API §3.3 with markdown-it-py's own inline linkify rule."""
    return MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
        ["linkify", "table", "strikethrough"]
    )


def _timed_render(body: str) -> float:
    start = time.perf_counter()
    comments._render(body)  # uncached
    return time.perf_counter() - start


@pytest.mark.parametrize(
    ("body", "budget"),
    [
        # upstream linkify searched the whole pending text before every "://": 0.5 s
        (("://" * 3334)[:10000], 0.15),
        (("<http://" * 1250)[:10000], 0.15),
        (("a://" * 2500)[:10000], 0.15),
        ("x" * 9000 + "http://example.org " * 52, 0.15),
        # unclosed brackets are quadratic in markdown-it itself (about 0.15 s locally);
        # the budget only guards against anything worse
        ("![" * 5000, 1.0),
    ],
)
def test_crafted_comment_bodies_render_in_bounded_time(body: str, budget: float) -> None:
    assert len(body) <= 10_000
    assert min(_timed_render(body) for _ in range(2)) < budget


@pytest.mark.parametrize(
    "body",
    [
        "see http://example.org and https://a.example/b?c=d#e, ftp://f.example/g",
        "mailto://x Mailto:a@b.example HTTP://EXAMPLE.ORG/X",
        "foo.http://x.example xhttp://a.example 1http://a.example +http://a.example",
        "a" * 70 + "http://a.example " + "b" * 64 + "https://c.example",
        "javascript://x a-b+c.d://e.example <http://a.example> [x](http://a.example)",
        "**http://bold.example/*** _https://em.example_ `http://code.example`",
        "x://y http://example.org/://z http://://",
        "Дія: https://diia.example/шлях?q=1 та www.example.org і user@example.org",
    ],
)
def test_the_linear_linkify_rule_renders_like_markdown_it(body: str) -> None:
    upstream = _upstream_markdown()
    assert comments._MARKDOWN.render(body) == upstream.render(body)


def test_serialised_comments_are_rendered_once(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = comments._render

    def counting(body: str) -> str:
        calls.append(body)
        return original(body)

    monkeypatch.setattr(comments, "_render", counting)
    monkeypatch.setattr(comments, "_RENDERED", comments.RenderCache(1_000_000))
    with db.session() as session:
        project_id = create_project(session).entity_id
        first = create_comment(session, project_id, "Cached **body** zq1", ALICE).entity_id
        create_comment(session, project_id, "Cached **body** zq1", BOB)  # same text
        with read_transaction(session):
            rows = load_rows(session, COMMENT, [first])
            assert serialize_comments(session, rows)[0]["body_html"].startswith("<p>Cached")
            serialize_comments(session, rows)
        feed = comments_listing(session, {"subject_id": project_id})
        assert len(feed["threads"]) == 2
    assert calls == ["Cached **body** zq1"]


def test_the_render_cache_is_bounded_by_characters() -> None:
    cache = comments.RenderCache(100)
    cache.put("a" * 10, "x" * 30)
    cache.put("b" * 10, "y" * 30)
    assert cache.get("a" * 10) == "x" * 30  # now the most recently used
    cache.put("c" * 10, "z" * 30)  # 120 > 100: the least recently used ("b") goes
    assert cache.get("b" * 10) is None
    assert cache.get("a" * 10) == "x" * 30 and cache.get("c" * 10) == "z" * 30
    assert cache.chars == 80 and len(cache) == 2
    cache.put("d", "w" * 200)  # larger than the whole cache: not cached
    assert cache.get("d") is None and cache.chars == 80
