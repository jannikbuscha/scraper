"""Revision lookups and representations (docs/DATA_MODEL.md §6.3, docs/API.md §3.2).

``RevisionSummary`` = ``{id, version, at, author, channel, action, note, changed_fields,
restored_from, restored_from_version, batch_id, run_id, proposal_id}``; ``RevisionFull``
adds ``snapshot``, ``diff`` and ``schema_revision``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import Revision
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.registry import EntityTypeSpec
from mdt.domain.snapshots import Diff, changed_fields, diff_snapshots


def get_revision(session: Session, entity_id: str, version: int) -> Revision | None:
    """The revision of ``entity_id`` with ``version``, or None."""
    return session.scalars(
        select(Revision).where(Revision.entity_id == entity_id, Revision.version == version)
    ).first()


def latest_revision(session: Session, entity_id: str) -> Revision | None:
    """The newest revision of ``entity_id``, or None."""
    return session.scalars(
        select(Revision).where(Revision.entity_id == entity_id).order_by(Revision.version.desc())
    ).first()


def revision_summary(revision: Revision) -> dict[str, Any]:
    """The RevisionSummary representation."""
    return {
        "id": revision.id,
        "version": revision.version,
        "at": revision.at,
        "author": revision.author,
        "channel": revision.channel,
        "action": revision.action,
        "note": revision.note,
        "changed_fields": changed_fields(revision.diff or {}),
        "restored_from": revision.restored_from,
        "restored_from_version": revision.restored_from_version,
        "batch_id": revision.batch_id,
        "run_id": revision.run_id,
        "proposal_id": revision.proposal_id,
    }


def revision_full(revision: Revision) -> dict[str, Any]:
    """The RevisionFull representation."""
    return {
        **revision_summary(revision),
        "snapshot": revision.snapshot,
        "diff": revision.diff,
        "schema_revision": revision.schema_revision,
    }


def diff_versions(
    session: Session, spec: EntityTypeSpec, entity_id: str, from_version: int, to_version: int
) -> tuple[Diff, list[str]]:
    """The diff between two versions computed from their snapshots (``from`` is the older
    side; ``0`` is the empty state before creation). Returns ``(diff, not_recorded)``."""
    if from_version < 0 or to_version < 1 or from_version >= to_version:
        raise ValidationError.single("from", "from must be older than to (0 = before creation)")
    new = get_revision(session, entity_id, to_version)
    old = get_revision(session, entity_id, from_version) if from_version else None
    if new is None or (from_version and old is None):
        raise NotFoundError("Version not found")
    return diff_snapshots(spec, old.snapshot if old else None, new.snapshot)
