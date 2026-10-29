"""UTC timestamps (docs/DATA_MODEL.md §1.1).

Every stored timestamp is a string ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` produced by
:func:`utc_now` or :func:`format_timestamp`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")

# Accepted on input and normalised to TIMESTAMP_FORMAT: ISO 8601 with seconds optional,
# 0-9 fractional digits and an explicit offset ("Z" or "+HH:MM"). Naive values are refused.
_INPUT_TIMESTAMP_RE = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})[T ](?P<h>[0-9]{2}):(?P<m>[0-9]{2})"
    r"(?::(?P<s>[0-9]{2})(?:\.(?P<f>[0-9]{1,9}))?)?"
    r"(?P<tz>Z|z|[+-][0-9]{2}:[0-9]{2})$"
)


def _storage_format(value: datetime) -> str:
    """The storage format of a UTC datetime."""
    return value.replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


def utc_now() -> str:
    """Return the current UTC time in the storage format."""
    return _storage_format(datetime.now(UTC))


def format_timestamp(value: datetime) -> str:
    """Format an aware UTC datetime in the storage format.

    Raises ``ValueError`` for naive datetimes or datetimes with a non-zero UTC offset.
    """
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("naive datetimes are not allowed")
    if offset != timedelta(0):
        raise ValueError("only UTC datetimes are allowed")
    return _storage_format(value.astimezone(UTC))


def is_timestamp(value: str) -> bool:
    """Return True if ``value`` is exactly in the storage format and a real instant."""
    if not TIMESTAMP_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def parse_timestamp(value: str) -> datetime:
    """Parse a storage-format timestamp into an aware UTC datetime."""
    if not is_timestamp(value):
        raise ValueError("not a timestamp in the storage format")
    return datetime.strptime(value, TIMESTAMP_FORMAT).replace(tzinfo=UTC)


def normalize_timestamp_input(value: str) -> str:
    """Normalise an ISO 8601 timestamp with an explicit offset to the storage format.

    Raises ``ValueError`` for anything else (naive timestamps, impossible dates).
    """
    if is_timestamp(value):
        return value
    match = _INPUT_TIMESTAMP_RE.fullmatch(value)
    if not match:
        raise ValueError("not an ISO 8601 timestamp with time zone")
    fraction = (match.group("f") or "0")[:6].ljust(6, "0")
    tz = match.group("tz").upper()
    text = (
        f"{match.group('date')}T{match.group('h')}:{match.group('m')}:"
        f"{match.group('s') or '00'}.{fraction}{'+00:00' if tz == 'Z' else tz}"
    )
    return _storage_format(datetime.fromisoformat(text).astimezone(UTC))


def timestamp_date(value: str) -> date:
    """Return the UTC calendar date of a storage-format timestamp."""
    return parse_timestamp(value).date()
