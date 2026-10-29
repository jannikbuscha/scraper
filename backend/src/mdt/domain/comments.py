"""Comments (docs/DATA_MODEL.md §6.6, docs/API.md §3.3).

Comments go through the same write path as entities (``entity_type = comment``); every
change creates a revision. ``body_html`` is rendered on read by :func:`render_markdown`
and never stored; rendered bodies are kept in a bounded in-memory cache, so a comment is
rendered once per process however often it is read.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from typing import Any, Final

import nh3
from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import Revision
from mdt.db.session import write_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import Problems, ValidationError
from mdt.domain.records import load_row
from mdt.domain.registry import COMMENT, ENTITY_TYPES, type_of_id
from mdt.domain.revisions import restore_version, soft_delete, undelete
from mdt.domain.writes import (
    ChangeResult,
    WriteUnit,
    clean_note,
    create_record,
    ensure_live,
    normalize_changes,
    require_row,
    snapshot_of,
    update_record,
)

# --------------------------------------------------------------------------------------
# Markdown rendering (API §3.3)
# --------------------------------------------------------------------------------------

#: The scheme before ``://`` (markdown-it-py's ``SCHEME_RE``).
_SCHEME_RE: Final = re.compile(r"(?:^|[^a-z0-9.+-])([a-z][a-z0-9.+-]*)$", re.IGNORECASE)
#: How much of the pending text is searched for that scheme. linkify-it only accepts
#: the schemes ``http:``, ``https:``, ``ftp:``, ``mailto:`` and ``//`` right at the
#: start of the text it is given, so a longer run of scheme characters never matches
#: and searching a bounded tail finds exactly what searching the whole text finds.
_SCHEME_TAIL: Final = 64


def _linkify_inline(state: StateInline, silent: bool) -> bool:
    """markdown-it-py's inline ``linkify`` rule (``rules_inline/linkify.py``, MIT
    licence) with one change: the scheme is looked for in the last
    :data:`_SCHEME_TAIL` characters of the pending text instead of in all of it.

    Upstream runs ``SCHEME_RE.search(state.pending)`` before every ``://``; the regex is
    anchored at the end, but ``search`` still tries every start position, and the
    pending text grows with the body. That is quadratic: a comment of 10 000 characters
    of ``://`` took half a second to render, on every read. The output is identical
    (tests compare it with the upstream rule)."""
    if not state.md.options.linkify or state.linkLevel > 0:
        return False
    if not state.md.linkify:
        raise ModuleNotFoundError("Linkify enabled but not installed.")
    pos = state.pos
    if (
        pos + 3 > state.posMax
        or state.src[pos] != ":"
        or state.src[pos + 1] != "/"
        or state.src[pos + 2] != "/"
    ):
        return False
    if not (match := _SCHEME_RE.search(state.pending[-_SCHEME_TAIL:])):
        return False
    proto = match.group(1)
    if not (link := state.md.linkify.match_at_start(state.src[pos - len(proto) :])):
        return False
    url: str = link.url.rstrip("*")  # a trailing '*' belongs to emphasis
    full_url = state.md.normalizeLink(url)
    if not state.md.validateLink(full_url):
        return False
    if not silent:
        state.pending = state.pending[: -len(proto)]
        token = state.push("link_open", "a", 1)
        token.attrs = {"href": full_url}
        token.markup = "linkify"
        token.info = "auto"
        token = state.push("text", "", 0)
        token.content = state.md.normalizeLinkText(url)
        token = state.push("link_close", "a", -1)
        token.markup = "linkify"
        token.info = "auto"
    state.pos += len(url) - len(proto)
    return True


def _markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
        ["linkify", "table", "strikethrough"]
    )
    md.inline.ruler.at("linkify", _linkify_inline)
    return md


_MARKDOWN = _markdown()
ALLOWED_TAGS = frozenset(
    {
        "p", "br", "strong", "em", "code", "pre", "blockquote", "ul", "ol", "li", "a",
        "h1", "h2", "h3", "h4", "hr", "table", "thead", "tbody", "tr", "th", "td", "s", "del",
    }
)  # fmt: skip
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "th": {"align", "colspan", "rowspan"},
    "td": {"align", "colspan", "rowspan"},
    "ol": {"start"},
}
URL_SCHEMES = frozenset({"http", "https", "mailto"})
LINK_REL = "noopener noreferrer nofollow"


def _attribute_filter(tag: str, attribute: str, value: str) -> str | None:
    """Drop protocol-relative links (``//host``), which the scheme allowlist lets pass."""
    if tag == "a" and attribute == "href" and value.strip().startswith("//"):
        return None
    return value


class RenderCache:
    """A thread-safe LRU cache of rendered bodies, bounded by the total number of
    characters of its keys and values (not by entries), so large crafted bodies cannot
    make it grow beyond the bound. Entries larger than the bound are not cached."""

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self._items: OrderedDict[str, str] = OrderedDict()
        self._chars = 0
        self._lock = threading.Lock()

    @property
    def chars(self) -> int:
        """Characters held (keys and values)."""
        return self._chars

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: str) -> str | None:
        """The cached value (marked as recently used), or None."""
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: str, value: str) -> None:
        """Cache ``value``; the least recently used entries make room."""
        size = len(key) + len(value)
        if size > self.max_chars:
            return
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return
            self._items[key] = value
            self._chars += size
            while self._chars > self.max_chars:
                old_key, old_value = self._items.popitem(last=False)
                self._chars -= len(old_key) + len(old_value)

    def clear(self) -> None:
        """Forget everything."""
        with self._lock:
            self._items.clear()
            self._chars = 0


#: Rendered bodies by ``body_md``: 8 million characters, a few thousand typical
#: comments, at most about 32 MB.
RENDER_CACHE_CHARS: Final = 8_000_000
_RENDERED = RenderCache(RENDER_CACHE_CHARS)


def render_markdown(body_md: str) -> str:
    """Render a comment body to sanitised HTML, computed on read (API §3.3).

    The result depends only on ``body_md`` (and the renderer of this process), so it is
    cached in memory: reading a thread renders each comment once per process instead of
    on every request. Nothing is stored; a changed sanitiser applies after a restart.
    """
    cached = _RENDERED.get(body_md)
    if cached is None:
        cached = _render(body_md)
        _RENDERED.put(body_md, cached)
    return cached


def _render(body_md: str) -> str:
    """markdown-it-py, then nh3.

    ``"*": set()`` turns off nh3's default generic attributes (``title``, ``lang``), so
    only the attributes of :data:`ALLOWED_ATTRIBUTES` survive.
    """
    html = _MARKDOWN.render(body_md)
    attributes = {tag: set(attrs) for tag, attrs in ALLOWED_ATTRIBUTES.items()}
    attributes["*"] = set()
    return nh3.clean(
        html,
        tags=set(ALLOWED_TAGS),
        attributes=attributes,
        generic_attribute_prefixes=set(),
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
        attribute_filter=_attribute_filter,
    )


# --------------------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------------------


def _check_body(unit: WriteUnit, provided: Mapping[str, Any]) -> None:
    body = provided.get("body_md")
    limit = unit.settings.max_comment_chars
    if isinstance(body, str) and len(body) > limit:
        raise ValidationError.single("body_md", f"must be at most {limit} characters")


def _thread_values(unit: WriteUnit, provided: dict[str, Any]) -> dict[str, Any]:
    """Validate subject, field and parent; return the values set by the domain layer."""
    problems = Problems()
    subject_id = provided.get("subject_id")
    subject_type = type_of_id(subject_id) if subject_id else None
    if subject_type == "comment":
        problems.add("subject_id", "Comments cannot be the subject of a comment")
    field_name = provided.get("field")
    if field_name and subject_type in ENTITY_TYPES:
        subject_spec = ENTITY_TYPES[subject_type]
        if not subject_spec.has_field(field_name) or subject_spec.field(field_name).internal:
            problems.add("field", "is not a field of the subject's entity type")
    extra: dict[str, Any] = {"status": "open"}
    parent_id = provided.get("parent_id")
    if parent_id:
        parent = load_row(unit.session, COMMENT, parent_id)
        if parent is None:
            problems.add("parent_id", "refers to a comment that does not exist")
        elif parent["parent_id"] is not None:
            problems.add("parent_id", "Replies must answer a root comment")
        elif parent["subject_id"] != subject_id:
            problems.add("parent_id", "The root comment belongs to another subject")
        elif parent["deleted_at"] is not None:
            problems.add("parent_id", "A deleted thread cannot be answered")
        elif field_name and field_name != parent["field"]:
            problems.add("field", "A reply belongs to the field of its root comment")
        else:
            extra = {"status": None, "field": parent["field"]}
    problems.raise_if_any()
    return extra


def create_comment_from_changes(
    session: Session, changes: Mapping[str, Any], actor: Actor, *, note: str | None = None
) -> ChangeResult:
    """Create a comment from ``{subject_id, field, parent_id, body_md}``.

    Roots start ``open``; replies have status null and the field of their root.
    """
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        provided = normalize_changes(unit, changes, creating=True)
        _check_body(unit, provided)
        extra = _thread_values(unit, provided)
        if "field" in extra:
            provided.pop("field", None)
        return create_record(unit, provided, note=clean, batch_id=None, extra_values=extra)


def create_comment(
    session: Session,
    subject_id: str,
    body_md: str,
    actor: Actor,
    *,
    field: str | None = None,
    parent_id: str | None = None,
) -> ChangeResult:
    """Create a root comment or a reply."""
    return create_comment_from_changes(
        session,
        {"subject_id": subject_id, "field": field, "parent_id": parent_id, "body_md": body_md},
        actor,
    )


def edit_comment_from_changes(
    session: Session,
    comment_id: str,
    changes: Mapping[str, Any],
    actor: Actor,
    *,
    note: str | None = None,
    expected_version: int | None = None,
) -> ChangeResult:
    """Change a comment's body (the only editable field)."""
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        row = require_row(unit, comment_id)
        ensure_live(row)
        provided = normalize_changes(unit, changes, creating=False)
        _check_body(unit, provided)
        return update_record(
            unit,
            row,
            provided,
            note=clean,
            expected_version=expected_version,
            batch_id=None,
            conflict_action="comment",
        )


def edit_comment(
    session: Session,
    comment_id: str,
    body_md: str,
    actor: Actor,
    *,
    expected_version: int | None,
    note: str | None = None,
) -> ChangeResult:
    """Edit a comment's Markdown body."""
    return edit_comment_from_changes(
        session,
        comment_id,
        {"body_md": body_md},
        actor,
        note=note,
        expected_version=expected_version,
    )


def _set_status(
    session: Session,
    comment_id: str,
    actor: Actor,
    status: str,
    expected_version: int | None,
    note: str | None,
) -> ChangeResult:
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, COMMENT, actor)
        row = require_row(unit, comment_id)
        if row["parent_id"] is not None:
            raise ValidationError.single("status", "Only root comments can be resolved or reopened")
        ensure_live(row)
        if row["status"] == status:
            # Idempotent: no revision and no version check (DATA_MODEL §6.6).
            return ChangeResult(
                "comment",
                comment_id,
                False,
                int(row["version"]),
                None,
                snapshot_of(COMMENT, row, None),
            )
        resolved = status == "resolved"
        values = normalize_changes(
            unit,
            {
                "status": status,
                "resolved_by": actor.by if resolved else None,
                "resolved_at": unit.ts if resolved else None,
            },
            creating=False,
            allow_system=True,
        )
        return update_record(
            unit,
            row,
            values,
            note=clean,
            expected_version=expected_version,
            batch_id=None,
            action="resolve" if resolved else "reopen",
            conflict_action="comment",
        )


def resolve_comment(
    session: Session,
    comment_id: str,
    actor: Actor,
    *,
    expected_version: int | None = None,
    note: str | None = None,
) -> ChangeResult:
    """Resolve a root comment (idempotent)."""
    return _set_status(session, comment_id, actor, "resolved", expected_version, note)


def reopen_comment(
    session: Session,
    comment_id: str,
    actor: Actor,
    *,
    expected_version: int | None = None,
    note: str | None = None,
) -> ChangeResult:
    """Reopen a resolved root comment (idempotent)."""
    return _set_status(session, comment_id, actor, "open", expected_version, note)


def delete_comment(
    session: Session,
    comment_id: str,
    actor: Actor,
    *,
    expected_version: int | None = None,
    note: str | None = None,
) -> ChangeResult:
    """Soft-delete a comment; deleting a root hides its thread (replies are unchanged)."""
    return soft_delete(
        session, "comment", comment_id, actor, note=note, expected_version=expected_version
    )


def undelete_comment(
    session: Session,
    comment_id: str,
    actor: Actor,
    *,
    expected_version: int | None = None,
    note: str | None = None,
) -> ChangeResult:
    """Undelete a comment."""
    return undelete(
        session, "comment", comment_id, actor, note=note, expected_version=expected_version
    )


def restore_comment(
    session: Session,
    comment_id: str,
    version: int,
    actor: Actor,
    *,
    expected_version: int | None = None,
    note: str | None = None,
) -> ChangeResult:
    """Restore a comment's body from an old version."""
    return restore_version(
        session, "comment", comment_id, version, actor, note=note, expected_version=expected_version
    )


# --------------------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------------------


def edited_comment_ids(session: Session, comment_ids: Iterable[str]) -> set[str]:
    """IDs of comments whose body changed in any revision after version 1."""
    ids = list(dict.fromkeys(comment_ids))
    if not ids:
        return set()
    edited: set[str] = set()
    for start in range(0, len(ids), 500):
        rows = session.execute(
            select(Revision.entity_id, Revision.diff).where(
                Revision.entity_id.in_(ids[start : start + 500]), Revision.version > 1
            )
        )
        for entity_id, diff in rows:
            if "body_md" in ((diff or {}).get("fields") or {}):
                edited.add(entity_id)
    return edited
