"""Prefixed ULID identifiers (docs/DATA_MODEL.md §1.1)."""

from __future__ import annotations

import re

from ulid import ULID

# Crockford base32 as produced by ULID (no I, L, O, U).
_ULID_RE = r"[0-9A-HJKMNP-TV-Z]{26}"
ID_RE = re.compile(rf"^(?P<prefix>[a-z]+)_(?P<ulid>{_ULID_RE})$")


def new_ulid() -> str:
    """Return a new ULID string (26 characters)."""
    return str(ULID())


def new_id(prefix: str) -> str:
    """Return a new identifier ``<prefix>_<ULID>``."""
    return f"{prefix}_{new_ulid()}"


def new_batch_id() -> str:
    """Return a new batch identifier for bulk edits and cascades (a plain ULID)."""
    return new_ulid()


def id_prefix(value: str) -> str | None:
    """Return the prefix of a well-formed identifier, else None."""
    match = ID_RE.fullmatch(value)
    return match.group("prefix") if match else None
