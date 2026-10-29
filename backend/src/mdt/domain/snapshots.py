"""Revision snapshots and diffs (docs/DATA_MODEL.md §6.3).

A snapshot is ``{"fields": {...}, "field_meta": {...}, "state": {...}}`` with every
tracked field in API representation. A diff has the optional sections ``fields``
(``{name: [old, new]}``), ``meta`` (``{name: {key: [old, new]}}``) and ``state``.
Version 0 is the empty state before creation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mdt.domain.fieldmeta import meta_diff
from mdt.domain.normalize import canonical_json, values_equal
from mdt.domain.registry import EntityTypeSpec

Snapshot = dict[str, Any]
Diff = dict[str, Any]


def make_snapshot(
    fields: Mapping[str, Any], field_meta: Mapping[str, Any], state: Mapping[str, Any]
) -> Snapshot:
    """Assemble a snapshot."""
    return {"fields": dict(fields), "field_meta": dict(field_meta), "state": dict(state)}


def _ordered_names(spec: EntityTypeSpec, *field_sets: Mapping[str, Any]) -> list[str]:
    known = [field.name for field in spec.tracked_fields]
    extra = sorted({name for fields in field_sets for name in fields} - set(known))
    return known + extra


def _equal(spec: EntityTypeSpec, name: str, old: Any, new: Any) -> bool:
    if spec.has_field(name):
        return values_equal(spec.field(name), old, new)
    return canonical_json(old) == canonical_json(new)


def diff_fields(
    spec: EntityTypeSpec, old: Mapping[str, Any] | None, new: Mapping[str, Any]
) -> tuple[dict[str, list[Any]], list[str]]:
    """Field changes between two ``fields`` objects and the fields not recorded in one
    of them. ``old=None`` is version 0: every non-empty field appears as ``[None, value]``."""
    changes: dict[str, list[Any]] = {}
    not_recorded: list[str] = []
    for name in _ordered_names(spec, old or {}, new):
        if old is None:
            if name in new and not _equal(spec, name, None, new[name]):
                changes[name] = [None, new[name]]
            continue
        if name not in old or name not in new:
            if name in old or name in new:
                not_recorded.append(name)
            continue
        if not _equal(spec, name, old[name], new[name]):
            changes[name] = [old[name], new[name]]
    return changes, not_recorded


def diff_state(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, list[Any]]:
    """State changes as ``{key: [old, new]}``."""
    return {
        key: [old.get(key), new.get(key)]
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key)
    }


def diff_snapshots(
    spec: EntityTypeSpec, old: Snapshot | None, new: Snapshot
) -> tuple[Diff, list[str]]:
    """The diff between two snapshots, plus the field names not recorded in one of them.

    ``old=None`` denotes version 0, the empty state before creation: its diff has no
    ``meta`` section (like the stored diff of a create revision), and ``state`` shows a
    later deletion. Empty sections are omitted.
    """
    fields, not_recorded = diff_fields(spec, old["fields"] if old else None, new["fields"])
    diff: Diff = {}
    if fields:
        diff["fields"] = fields
    if old is not None:
        meta = meta_diff(old.get("field_meta") or {}, new.get("field_meta") or {})
        if meta:
            diff["meta"] = meta
    state = diff_state((old or {}).get("state") or {}, new.get("state") or {})
    if state:
        diff["state"] = state
    return diff, not_recorded


def changed_fields(diff: Mapping[str, Any]) -> list[str]:
    """``changed_fields`` of a revision: the keys of ``diff.fields`` and ``diff.meta``, plus
    ``deleted`` if ``diff.state`` changes (DATA_MODEL §6.3)."""
    names = list(diff.get("fields") or {})
    names += [name for name in (diff.get("meta") or {}) if name not in names]
    if diff.get("state"):
        names.append("deleted")
    return names
