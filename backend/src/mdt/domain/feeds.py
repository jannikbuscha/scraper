"""Feeds and histories (docs/API.md §3.2-§3.4): recent changes, comment threads and the
comment feed, per-record revision lists, single revisions and diffs. Every public
function opens its own read transaction.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import ColumnElement, FromClause, Table, exists, func, or_, select
from sqlalchemy.orm import Session

from mdt.db.models import Comment, Revision, SavedView, SearchKey, VocabularyTerm
from mdt.db.session import read_transaction
from mdt.domain.actor import CHANNELS
from mdt.domain.clock import normalize_timestamp_input
from mdt.domain.dates import PartialDateError, parse_iso_date
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.history import diff_versions, get_revision, revision_full, revision_summary
from mdt.domain.labels import ref_infos, refs_payload
from mdt.domain.listquery import (
    QueryParams,
    last_param,
    param_pairs,
    parse_deleted,
    parse_paging,
    parse_search,
    split_list,
)
from mdt.domain.records import load_row
from mdt.domain.registry import COMMENT, ENTITY_TYPES, EntityTypeSpec, type_of_id
from mdt.domain.search import match_subquery
from mdt.domain.serialize import diff_ref_ids, record_spec, revision_refs, serialize_comments
from mdt.domain.snapshots import changed_fields

ACTIONS: Final = (
    "create",
    "update",
    "verify",
    "delete",
    "undelete",
    "restore",
    "merge",
    "unmerge",
    "resolve",
    "reopen",
)
COMMENT_STATUSES: Final = ("open", "resolved")
#: ``field`` value that selects entity-level threads only.
ENTITY_LEVEL: Final = "-"
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _table(model: type[Any]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def _choices(name: str, raw: str | None, allowed: Sequence[str]) -> list[str]:
    values = split_list(raw)
    if any(value not in allowed for value in values):
        raise ValidationError.single(name, f"must be one of {', '.join(allowed)}")
    return values


def _time_bound(name: str, raw: str | None, *, end: bool) -> str | None:
    """A ``since``/``until`` bound as a storage timestamp: a date is a UTC day (its
    first or last microsecond), a timestamp is used as given (both inclusive)."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    try:
        if _DATE_RE.fullmatch(value):
            day = parse_iso_date(value).isoformat()
            return f"{day}T23:59:59.999999Z" if end else f"{day}T00:00:00.000000Z"
        return normalize_timestamp_input(value)
    except (PartialDateError, ValueError) as exc:
        raise ValidationError.single(
            name, "must be a date (YYYY-MM-DD) or an ISO 8601 timestamp with time zone"
        ) from exc


# --------------------------------------------------------------------------------------
# GET /api/revisions
# --------------------------------------------------------------------------------------


def recent_changes(session: Session, params: QueryParams) -> dict[str, Any]:
    """``GET /api/revisions``: revisions of every type (comments, terms and saved views
    included), newest first, with filters on type, channel, action, time, entity, batch,
    collector run and accepted proposal."""
    pairs = param_pairs(params)
    revision = _table(Revision)
    conditions: list[ColumnElement[bool]] = []
    for name, allowed in (
        ("entity_type", tuple(ENTITY_TYPES)),
        ("channel", CHANNELS),
        ("action", ACTIONS),
    ):
        values = _choices(name, last_param(pairs, name), allowed)
        if values:
            conditions.append(revision.c[name].in_(values))
    since = _time_bound("since", last_param(pairs, "since"), end=False)
    if since is not None:
        conditions.append(revision.c.at >= since)
    until = _time_bound("until", last_param(pairs, "until"), end=True)
    if until is not None:
        conditions.append(revision.c.at <= until)
    for name in ("entity_id", "batch_id", "run_id", "proposal_id"):
        value = (last_param(pairs, name) or "").strip()
        if value:
            conditions.append(revision.c[name] == value)
    page, page_size = parse_paging(pairs)
    columns = [
        revision.c[name]
        for name in (
            "id",
            "entity_type",
            "entity_id",
            "version",
            "at",
            "author",
            "channel",
            "action",
            "note",
            "diff",
            "restored_from_version",
            "batch_id",
            "run_id",
            "proposal_id",
        )
    ]
    with read_transaction(session):
        total = session.execute(
            select(func.count()).select_from(revision).where(*conditions)
        ).scalar_one()
        rows = [
            dict(row)
            for row in session.execute(
                select(*columns)
                .where(*conditions)
                .order_by(revision.c.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            ).mappings()
        ]
        labels = ref_infos(session, [row["entity_id"] for row in rows])
        contexts = _contexts(session, rows)
    items = []
    for row in rows:
        info = labels.get(row["entity_id"])
        items.append(
            {
                "id": row["id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "entity_label": info.label if info else row["entity_id"],
                "version": row["version"],
                "at": row["at"],
                "author": row["author"],
                "channel": row["channel"],
                "action": row["action"],
                "note": row["note"],
                "changed_fields": changed_fields(row["diff"] or {}),
                "restored_from_version": row["restored_from_version"],
                "batch_id": row["batch_id"],
                "run_id": row["run_id"],
                "proposal_id": row["proposal_id"],
                "context": contexts.get(row["entity_id"]),
            }
        )
    return {"items": items, "total": int(total), "page": page, "page_size": page_size}


def _contexts(session: Session, rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """``context`` per entity: comment → subject and field (plus ``parent_id`` for
    replies), vocabulary term → vocabulary, saved view → table."""
    by_type: dict[str, set[str]] = {"comment": set(), "vocabulary_term": set(), "saved_view": set()}
    for row in rows:
        if row["entity_type"] in by_type:
            by_type[row["entity_type"]].add(row["entity_id"])
    result: dict[str, dict[str, Any]] = {}
    if by_type["comment"]:
        comment = _table(Comment)
        for entity_id, subject_id, field, parent_id in session.execute(
            select(comment.c.id, comment.c.subject_id, comment.c.field, comment.c.parent_id).where(
                comment.c.id.in_(by_type["comment"])
            )
        ):
            result[entity_id] = {
                "subject_id": subject_id,
                "subject_type": type_of_id(subject_id),
                "field": field,
                "parent_id": parent_id,
            }
    for entity_type, model, column in (
        ("vocabulary_term", VocabularyTerm, "vocabulary"),
        ("saved_view", SavedView, "entity_type"),
    ):
        if by_type[entity_type]:
            table = _table(model)
            for entity_id, value in session.execute(
                select(table.c.id, table.c[column]).where(table.c.id.in_(by_type[entity_type]))
            ):
                result[entity_id] = {column: value}
    return result


# --------------------------------------------------------------------------------------
# GET /api/comments
# --------------------------------------------------------------------------------------


def _status(raw: str | None) -> str | None:
    if raw is None or raw in ("", "all"):
        return None
    if raw not in COMMENT_STATUSES:
        raise ValidationError.single("status", "must be open, resolved or all")
    return raw


def _deleted_condition(table: FromClause, mode: str) -> ColumnElement[bool] | None:
    column = table.c.deleted_at
    if mode == "exclude":
        return column.is_(None)
    if mode == "only":
        return column.is_not(None)
    return None


def comments_listing(session: Session, params: QueryParams) -> dict[str, Any]:
    """``GET /api/comments``: the threads of one subject (with ``subject_id``) or the
    comment feed, one item per thread (without).

    ``deleted`` applies to the thread roots: ``exclude`` shows live roots with their live
    replies, ``include`` everything, ``only`` the deleted roots with all their replies.
    The feed is ordered by last activity, newest first; with ``deleted=only`` by the
    deletion time of the root, newest first (the trash order, API §3.1).
    """
    pairs = param_pairs(params)
    status = _status(last_param(pairs, "status"))
    deleted = parse_deleted(last_param(pairs, "deleted"))
    subject_id = (last_param(pairs, "subject_id") or "").strip()
    if subject_id:
        field = last_param(pairs, "field")
        with read_transaction(session):
            return {"threads": _threads(session, subject_id, status, field, deleted)}
    return _comment_feed(session, pairs, status, deleted)


def _threads(
    session: Session, subject_id: str, status: str | None, field: str | None, deleted: str
) -> list[dict[str, Any]]:
    comment = _table(Comment)
    conditions = [comment.c.subject_id == subject_id, comment.c.parent_id.is_(None)]
    if status is not None:
        conditions.append(comment.c.status == status)
    if field == ENTITY_LEVEL:
        conditions.append(comment.c.field.is_(None))
    elif field:
        conditions.append(comment.c.field == field)
    root_deleted = _deleted_condition(comment, deleted)
    if root_deleted is not None:
        conditions.append(root_deleted)
    roots = [
        dict(row)
        for row in session.execute(
            select(comment)
            .where(*conditions)
            .order_by(comment.c.created_at.desc(), comment.c.id.desc())
        ).mappings()
    ]
    reply_conditions = [comment.c.parent_id.in_([root["id"] for root in roots])]
    if deleted == "exclude":
        reply_conditions.append(comment.c.deleted_at.is_(None))
    replies = (
        [
            dict(row)
            for row in session.execute(
                select(comment)
                .where(*reply_conditions)
                .order_by(comment.c.created_at, comment.c.id)
            ).mappings()
        ]
        if roots
        else []
    )
    serialized = {item["id"]: item for item in serialize_comments(session, roots + replies)}
    by_root: dict[str, list[dict[str, Any]]] = {root["id"]: [] for root in roots}
    for reply in replies:
        by_root[reply["parent_id"]].append(serialized[reply["id"]])
    return [{"root": serialized[root["id"]], "replies": by_root[root["id"]]} for root in roots]


def _comment_feed(
    session: Session, pairs: Sequence[tuple[str, str]], status: str | None, deleted: str
) -> dict[str, Any]:
    root = _table(Comment).alias("root")
    conditions: list[ColumnElement[bool]] = [root.c.parent_id.is_(None)]
    if status is not None:
        conditions.append(root.c.status == status)
    root_deleted = _deleted_condition(root, deleted)
    if root_deleted is not None:
        conditions.append(root_deleted)
    types = split_list(last_param(pairs, "entity_type"))
    if types:
        prefixes = []
        for name in types:
            spec = ENTITY_TYPES.get(name)
            if spec is None or not spec.curated:
                raise ValidationError.single("entity_type", "contains an unknown entity type")
            prefixes.append(f"{spec.prefix}_")
        conditions.append(or_(*(func.substr(root.c.subject_id, 1, len(p)) == p for p in prefixes)))
    q, match = parse_search(last_param(pairs, "q"))
    page, page_size = parse_paging(pairs)
    if q is not None:
        if match is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        matched = _matching_comment_ids(match)
        conditions.append(
            or_(root.c.id.in_(matched), _reply_exists(root, lambda r: r.c.id.in_(matched)))
        )
    reply = _table(Comment).alias("reply")
    live_reply = (reply.c.parent_id == root.c.id) & reply.c.deleted_at.is_(None)
    reply_count = select(func.count()).select_from(reply).where(live_reply).scalar_subquery()
    last_reply = (
        select(func.max(reply.c.updated_at)).select_from(reply).where(live_reply).scalar_subquery()
    )
    last_activity = func.max(root.c.updated_at, func.coalesce(last_reply, root.c.updated_at))
    # The trash (deleted=only) lists the newest deletion first, like the other deleted views.
    order = (
        (root.c.deleted_at.desc(), root.c.id.desc())
        if deleted == "only"
        else (last_activity.desc(), root.c.id.desc())
    )
    with read_transaction(session):
        total = session.execute(select(func.count()).select_from(root).where(*conditions))
        total_count = int(total.scalar_one())
        rows = [
            dict(row)
            for row in session.execute(
                select(
                    root, reply_count.label("reply_count"), last_activity.label("last_activity_at")
                )
                .where(*conditions)
                .order_by(*order)
                .limit(page_size)
                .offset((page - 1) * page_size)
            ).mappings()
        ]
        roots = serialize_comments(session, rows)
    items = [
        {
            "root": item,
            "reply_count": int(row["reply_count"]),
            "last_activity_at": row["last_activity_at"],
        }
        for item, row in zip(roots, rows, strict=True)
    ]
    return {"items": items, "total": total_count, "page": page, "page_size": page_size}


def _reply_exists(
    root: Any, condition: Callable[[Any], ColumnElement[bool]]
) -> ColumnElement[bool]:
    """A live reply of ``root`` satisfies ``condition`` (built on the reply alias)."""
    reply = _table(Comment).alias()
    return exists().where(
        reply.c.parent_id == root.c.id, reply.c.deleted_at.is_(None), condition(reply)
    )


def _matching_comment_ids(match: str) -> Any:
    """IDs of the comments whose text matches the FTS expression."""
    matches = match_subquery(match, documents=False)
    key = _table(SearchKey)
    return (
        select(key.c.entity_id)
        .select_from(key.join(matches, matches.c.fts_rowid == key.c.rowid))
        .where(key.c.entity_type == "comment")
    )


# --------------------------------------------------------------------------------------
# Revisions of one record
# --------------------------------------------------------------------------------------


def _require_record(session: Session, spec: EntityTypeSpec, entity_id: str) -> None:
    if load_row(session, spec, entity_id) is None:
        raise NotFoundError()


def entity_revisions(
    session: Session, entity_type: str, entity_id: str, params: QueryParams
) -> dict[str, Any]:
    """``GET …/{id}/revisions``: RevisionSummary list, newest first, with ``refs`` for
    the IDs in the listed diffs. ``entity_type`` may be ``comment``."""
    spec = record_spec(entity_type)
    page, page_size = parse_paging(param_pairs(params))
    with read_transaction(session):
        _require_record(session, spec, entity_id)
        total = session.execute(
            select(func.count()).select_from(Revision).where(Revision.entity_id == entity_id)
        ).scalar_one()
        revisions = list(
            session.scalars(
                select(Revision)
                .where(Revision.entity_id == entity_id)
                .order_by(Revision.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        items = [revision_summary(revision) for revision in revisions]
        refs = revision_refs(session, spec, revisions, snapshots=False)
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "refs": refs,
    }


def entity_revision(
    session: Session, entity_type: str, entity_id: str, version: int
) -> dict[str, Any]:
    """``GET …/{id}/revisions/{version}``: ``{"revision": RevisionFull, "refs"}``."""
    spec = record_spec(entity_type)
    with read_transaction(session):
        _require_record(session, spec, entity_id)
        revision = get_revision(session, entity_id, version)
        if revision is None:
            raise NotFoundError("Version not found")
        return {
            "revision": revision_full(revision),
            "refs": revision_refs(session, spec, [revision], snapshots=True),
        }


def entity_diff(
    session: Session, entity_type: str, entity_id: str, from_version: int, to_version: int
) -> dict[str, Any]:
    """``GET …/{id}/diff?from=&to=``: the diff computed from both snapshots (``from=0`` is
    the empty state before creation), the fields not recorded in one of them and refs."""
    spec = record_spec(entity_type)
    with read_transaction(session):
        _require_record(session, spec, entity_id)
        diff, not_recorded = diff_versions(session, spec, entity_id, from_version, to_version)
        refs = refs_payload(session, diff_ref_ids(spec, diff))
    return {
        "from": from_version,
        "to": to_version,
        "diff": diff,
        "not_recorded": not_recorded,
        "refs": refs,
    }


def revision_by_id(session: Session, revision_id: int) -> dict[str, Any]:
    """``GET /api/revisions/{revision_id}`` for any type, comments included."""
    with read_transaction(session):
        revision = session.get(Revision, revision_id)
        if revision is None:
            raise NotFoundError("Revision not found")
        spec = ENTITY_TYPES.get(revision.entity_type, COMMENT)
        labels = ref_infos(session, [revision.entity_id])
        info = labels.get(revision.entity_id)
        return {
            "revision": revision_full(revision),
            "entity_type": revision.entity_type,
            "entity_id": revision.entity_id,
            "entity_label": info.label if info else revision.entity_id,
            "refs": revision_refs(session, spec, [revision], snapshots=True),
        }
