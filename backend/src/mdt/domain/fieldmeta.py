"""Field provenance entries (docs/DATA_MODEL.md §5).

``field_meta`` maps a tracked field name to
``{src, by, at, locked, verified, evidence_id, restored_from_version, raw_snapshot_ids}``.
Entries are never removed; clearing a field writes an entry like any other change.
``raw_snapshot_ids`` (Phase 2) names the raw snapshots a collected value was parsed from;
entries written before Phase 2 lack the key, which reads as null.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mdt.domain.actor import Actor

#: Entry keys in their canonical order.
ENTRY_KEYS = (
    "src",
    "by",
    "at",
    "locked",
    "verified",
    "evidence_id",
    "restored_from_version",
    "raw_snapshot_ids",
)
#: Keys compared in diffs; ``at`` changes with every write and is left out.
DIFF_KEYS = tuple(key for key in ENTRY_KEYS if key != "at")


def takes_snapshots(actor: Actor) -> bool:
    """True if values written by ``actor`` record the snapshots they were parsed from:
    collector writes, and observed values a person accepts from a proposal (§5)."""
    return actor.channel == "collector" or (
        actor.channel == "ui" and actor.proposal_src is not None
    )


def source_of(actor: Actor, restored_src: str | None = None, *, observed: bool = False) -> str:
    """The ``src`` of a value written by ``actor`` (DATA_MODEL §5 table). ``observed``
    marks a value that an accepted proposal takes unchanged from its source."""
    channel = actor.channel
    if channel == "seed":
        return "seed"
    if channel == "import":
        return f"import:{actor.file}"
    if channel == "collector":
        return f"{actor.name}@{actor.run_id}"
    if channel == "ui" and observed and actor.proposal_src:
        return actor.proposal_src
    if channel in ("restore", "merge", "system") and restored_src:
        return restored_src
    return "manual"


def is_locked(actor: Actor) -> bool:
    """Collector values stay unlocked; every other channel locks the field."""
    return actor.channel != "collector"


def value_entry(
    actor: Actor,
    at: str,
    *,
    restored_src: str | None = None,
    restored_from_version: int | None = None,
    snapshots: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The entry for a value change: verification reset, provenance per channel.

    ``snapshots`` are the raw snapshots the value was parsed from. They are recorded on
    channel ``collector`` and, for a value taken unchanged from an accepted proposal, on
    channel ``ui`` (whose ``src`` is then the proposal's source); otherwise ignored.
    """
    recorded = snapshots is not None and takes_snapshots(actor)
    return {
        "src": source_of(actor, restored_src, observed=recorded),
        "by": actor.by,
        "at": at,
        "locked": is_locked(actor),
        "verified": "unverified",
        "evidence_id": None,
        "restored_from_version": restored_from_version,
        "raw_snapshot_ids": list(snapshots) if recorded and snapshots is not None else None,
    }


def verification_entry(
    previous: Mapping[str, Any] | None,
    actor: Actor,
    at: str,
    status: str,
    evidence_id: str | None,
) -> dict[str, Any]:
    """The entry after field verification: keeps the value's provenance, sets
    ``verified`` and ``evidence_id`` and locks the field (DATA_MODEL §5, §6.4)."""
    entry = dict(previous) if previous else value_entry(actor, at)
    entry.update(
        {
            "at": at,
            "locked": True,
            "verified": status,
            "evidence_id": evidence_id if status == "verified" else None,
        }
    )
    return {key: entry.get(key) for key in ENTRY_KEYS}


def seed_may_overwrite(entry: Mapping[str, Any] | None) -> bool:
    """The seed overwrite rule (DATA_MODEL §9): no entry, or an unverified,
    never restored entry written by the seed."""
    if entry is None:
        return True
    return (
        entry.get("by") == "seed"
        and entry.get("verified") == "unverified"
        and entry.get("restored_from_version") is None
    )


def entry_diff(
    old: Mapping[str, Any] | None, new: Mapping[str, Any] | None
) -> dict[str, list[Any]]:
    """Changed keys of one entry (without ``at``) as ``{key: [old, new]}``."""
    old = old or {}
    new = new or {}
    return {
        key: [old.get(key), new.get(key)]
        for key in DIFF_KEYS
        if old.get(key) != new.get(key) or type(old.get(key)) is not type(new.get(key))
    }


def meta_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, dict[str, list[Any]]]:
    """``diff.meta`` between two ``field_meta`` objects."""
    result = {}
    for name in sorted(set(old) | set(new)):
        changes = entry_diff(old.get(name), new.get(name))
        if changes:
            result[name] = changes
    return result
