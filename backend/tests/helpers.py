"""Helpers for building synthetic records and inspecting stored state."""

from __future__ import annotations

import itertools
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from mdt.db.models import Organization, Revision
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.history import latest_revision
from mdt.domain.records import (
    Row,
    field_meta_of,
    load_links,
    load_row,
    state_of,
    tracked_values,
)
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.revisions import apply_change
from mdt.domain.writes import ChangeResult
from tests import synthetic
from tests.conftest import Db

USER = Actor.ui()

_counter = itertools.count(1)


def unique_slug(prefix: str = "example") -> str:
    """A slug that no other test record uses."""
    return f"{prefix}-{next(_counter)}"


def project_data(**overrides: Any) -> dict[str, Any]:
    """A valid project payload (a project needs a scope note on create)."""
    data: dict[str, Any] = {
        "slug": unique_slug(),
        "name_en": "Example project",
        "scope_note": "Synthetic scope note.",
    }
    data.update(overrides)
    return data


def create_project(session: Session, actor: Actor = USER, **overrides: Any) -> ChangeResult:
    """Create a project with synthetic values."""
    return apply_change(session, "project", None, project_data(**overrides), actor)


def create_service(
    session: Session, project_id: str, actor: Actor = USER, **overrides: Any
) -> ChangeResult:
    """Create a service of ``project_id``."""
    data: dict[str, Any] = {"project_id": project_id, "name_en": "Example service"}
    data.update(overrides)
    return apply_change(session, "service", None, data, actor)


def create_event(
    session: Session,
    subject_id: str,
    event_type: str = "launch",
    date: str | None = None,
    actor: Actor = USER,
    **overrides: Any,
) -> ChangeResult:
    """Create an event; a date gets the matching basis unless one is given."""
    data: dict[str, Any] = {"subject_id": subject_id, "event_type": event_type}
    if date is not None:
        data["date"] = date
        data["date_basis"] = (
            "archive_upper_bound" if event_type == "first_archived" else "stated_in_source"
        )
    data.update(overrides)
    return apply_change(session, "event", None, data, actor)


def create_evidence(
    session: Session, subject_id: str, field_name: str, actor: Actor = USER, **overrides: Any
) -> ChangeResult:
    """Create a URL evidence row that targets ``field:<field_name>``."""
    data: dict[str, Any] = {
        "subject_id": subject_id,
        "target": f"field:{field_name}",
        "url": "https://example.org/source",
        "quote": "Example quote.",
    }
    data.update(overrides)
    return apply_change(session, "evidence", None, data, actor)


def load(session: Session, entity_type: str, entity_id: str) -> Row:
    """The stored row (in a short read transaction)."""
    with read_transaction(session):
        row = load_row(session, ENTITY_TYPES[entity_type], entity_id)
    assert row is not None
    return row


def fields_of(session: Session, entity_type: str, entity_id: str) -> dict[str, Any]:
    """Every tracked field of the stored row in API representation."""
    spec = ENTITY_TYPES[entity_type]
    with read_transaction(session):
        row = load_row(session, spec, entity_id)
        assert row is not None
        links = load_links(session, [entity_id])[entity_id] if spec.has_field("links") else None
        return tracked_values(spec, row, links)


def revisions_of(session: Session, entity_id: str) -> list[Revision]:
    """All revisions of an entity, oldest first."""
    with read_transaction(session):
        revisions = list(
            session.scalars(
                select(Revision).where(Revision.entity_id == entity_id).order_by(Revision.version)
            )
        )
        session.expunge_all()
    return revisions


def revision_count(session: Session) -> int:
    """Number of revisions in the database."""
    with read_transaction(session):
        return int(session.execute(select(func.count()).select_from(Revision)).scalar_one())


def fts_row(session: Session, entity_id: str, table: str = "fts_entity") -> tuple[str, ...] | None:
    """The FTS row of an entity (``fts_entity``: ``(body,)``; ``fts_document``:
    ``(title, body)``), or None."""
    columns = "title, body" if table == "fts_document" else "body"
    with read_transaction(session):
        row = session.execute(
            text(
                f"SELECT {columns} FROM {table} WHERE rowid = "
                "(SELECT rowid FROM search_key WHERE entity_id = :id)"
            ),
            {"id": entity_id},
        ).first()
    return tuple(row) if row is not None else None


def focal_org_id(session: Session) -> str:
    """ID of the seeded focal organisation."""
    with read_transaction(session):
        value = session.execute(
            select(Organization.id).where(Organization.seed_key == synthetic.FOCAL_ORG_SEED_KEY)
        ).scalar_one()
    return str(value)


def assert_matches_latest_snapshot(db: Db, entity_type: str, entity_id: str) -> None:
    """Reloading the row in a new session gives the version, fields, ``field_meta`` and
    state of its latest revision snapshot (DATA_MODEL §6.1 required test)."""
    spec = ENTITY_TYPES[entity_type]
    with db.session() as session, read_transaction(session):
        row = load_row(session, spec, entity_id)
        assert row is not None
        links = load_links(session, [entity_id])[entity_id] if spec.has_field("links") else None
        revision = latest_revision(session, entity_id)
        assert revision is not None
        assert revision.version == row["version"]
        assert revision.snapshot == {
            "fields": tracked_values(spec, row, links),
            "field_meta": field_meta_of(spec, row),
            "state": state_of(spec, row),
        }
