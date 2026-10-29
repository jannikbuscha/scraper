"""The 409 ``conflict`` payload (docs/DATA_MODEL.md §6.5)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.orm import Session

from mdt.domain.history import get_revision, revision_summary, revisions_between
from mdt.domain.labels import refs_payload
from mdt.domain.normalize import values_equal
from mdt.domain.records import Row, field_meta_of, state_of, tracked_values
from mdt.domain.registry import EntityTypeSpec
from mdt.domain.snapshots import diff_fields

ConflictAction = str  # patch, delete, undelete, verify, restore, bulk, comment


def _ref_ids(spec: EntityTypeSpec, values: Mapping[str, Any] | None) -> Iterable[str]:
    if not values:
        return []
    ids: list[str] = []
    for field in spec.fields:
        value = values.get(field.name)
        if field.type == "ref" and isinstance(value, str):
            ids.append(value)
        elif field.type == "doc_links" and isinstance(value, list):
            ids.extend(link["subject_id"] for link in value if isinstance(link, dict))
    return ids


def conflict_payload(
    session: Session,
    spec: EntityTypeSpec,
    row: Row,
    links: list[dict[str, Any]] | None,
    *,
    action: ConflictAction,
    base_version: int,
    your_changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Everything the client needs to resolve the conflict; nothing is written."""
    entity_id = row["id"]
    current_version = int(row["version"])
    current = tracked_values(spec, row, links)
    current_meta = field_meta_of(spec, row)
    base_revision = (
        get_revision(session, entity_id, base_version)
        if 1 <= base_version <= current_version
        else None
    )
    base_snapshot = base_revision.snapshot if base_revision is not None else None
    base = base_snapshot["fields"] if base_snapshot else None

    if base is not None:
        changes, _ = diff_fields(spec, base, current)
        changed_since_base = list(changes)
    else:
        # Without a base every field may have changed.
        changed_since_base = [field.name for field in spec.tracked_fields]

    conflicting = [
        name
        for name, value in your_changes.items()
        if name in changed_since_base
        and spec.has_field(name)
        and not values_equal(spec.field(name), value, current.get(name))
    ]

    meta_changed: dict[str, dict[str, list[Any]]] = {}
    if base_snapshot is not None:
        base_meta = base_snapshot.get("field_meta") or {}
        for name in sorted(set(base_meta) | set(current_meta)):
            # A field without an entry has never been verified.
            old = (base_meta.get(name) or {}).get("verified") or "unverified"
            new = (current_meta.get(name) or {}).get("verified") or "unverified"
            if old != new:
                meta_changed[name] = {"verified": [old, new]}

    intervening = (
        [
            revision_summary(revision)
            for revision in revisions_between(
                session, entity_id, max(base_version, 0), current_version
            )
        ]
        if base_version < current_version
        else []
    )
    ids = [*_ref_ids(spec, base), *_ref_ids(spec, current), *_ref_ids(spec, your_changes)]
    return {
        "action": action,
        "entity_type": spec.name,
        "entity_id": entity_id,
        "base_version": base_version,
        "current_version": current_version,
        "base": base,
        "current": current,
        "base_state": base_snapshot.get("state") if base_snapshot else None,
        "current_state": state_of(spec, row),
        "changed_since_base": changed_since_base,
        "your_changes": dict(your_changes),
        "conflicting_fields": conflicting,
        "meta_changed_since_base": meta_changed,
        "intervening": intervening,
        "refs": refs_payload(session, ids),
    }
