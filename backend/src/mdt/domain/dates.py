"""Calendar dates and partial dates (docs/DATA_MODEL.md §1.1).

A partial date is one of the canonical strings ``YYYY``, ``YYYY-Qn``, ``YYYY-MM`` or
``YYYY-MM-DD`` (years 1900-2100). It is stored as an inclusive interval
``<name>_start``/``<name>_end`` plus ``<name>_precision``; the canonical string can be
rebuilt from those three columns.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

Precision = Literal["day", "month", "quarter", "year"]
PRECISIONS: tuple[Precision, ...] = ("day", "month", "quarter", "year")

MIN_YEAR = 1900
MAX_YEAR = 2100
#: Start of the interval used for dates with basis ``archive_upper_bound`` (§8.2).
EARLIEST_DATE = date(MIN_YEAR, 1, 1)

_YEAR_RE = re.compile(r"^([0-9]{4})$")
_QUARTER_RE = re.compile(r"^([0-9]{4})-Q([1-4])$")
_MONTH_RE = re.compile(r"^([0-9]{4})-([0-9]{2})$")
_DAY_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")


class PartialDateError(ValueError):
    """The value is not a canonical partial date."""


@dataclass(frozen=True)
class PartialDate:
    """A parsed partial date: canonical value, inclusive interval and precision."""

    value: str
    start: date
    end: date
    precision: Precision

    @property
    def start_iso(self) -> str:
        """Interval start as ``YYYY-MM-DD``."""
        return self.start.isoformat()

    @property
    def end_iso(self) -> str:
        """Interval end as ``YYYY-MM-DD``."""
        return self.end.isoformat()


def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise PartialDateError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_partial_date(value: str) -> PartialDate:
    """Parse a canonical partial date string; raise :class:`PartialDateError` otherwise."""
    if match := _DAY_RE.fullmatch(value):
        year, month, day = (int(part) for part in match.groups())
        _check_year(year)
        try:
            day_date = date(year, month, day)
        except ValueError as exc:
            raise PartialDateError("not a valid calendar date") from exc
        return PartialDate(value, day_date, day_date, "day")
    if match := _MONTH_RE.fullmatch(value):
        year, month = (int(part) for part in match.groups())
        _check_year(year)
        if not 1 <= month <= 12:
            raise PartialDateError("month must be between 01 and 12")
        return PartialDate(value, date(year, month, 1), _month_end(year, month), "month")
    if match := _QUARTER_RE.fullmatch(value):
        year, quarter = (int(part) for part in match.groups())
        _check_year(year)
        first_month = 3 * (quarter - 1) + 1
        return PartialDate(
            value, date(year, first_month, 1), _month_end(year, first_month + 2), "quarter"
        )
    if match := _YEAR_RE.fullmatch(value):
        year = int(match.group(1))
        _check_year(year)
        return PartialDate(value, date(year, 1, 1), date(year, 12, 31), "year")
    raise PartialDateError("expected YYYY, YYYY-Qn, YYYY-MM or YYYY-MM-DD")


def is_partial_date(value: str) -> bool:
    """Return True if ``value`` is a canonical partial date."""
    try:
        parse_partial_date(value)
    except PartialDateError:
        return False
    return True


def format_partial_date(start: str | date, precision: str) -> str:
    """Rebuild the canonical string from the interval start and the precision."""
    start_date = start if isinstance(start, date) else parse_iso_date(start)
    if precision == "day":
        return start_date.isoformat()
    if precision == "month":
        return f"{start_date.year:04d}-{start_date.month:02d}"
    if precision == "quarter":
        return f"{start_date.year:04d}-Q{(start_date.month - 1) // 3 + 1}"
    if precision == "year":
        return f"{start_date.year:04d}"
    raise PartialDateError(f"unknown precision {precision!r}")


def partial_date_from_columns(
    start: str | None, end: str | None, precision: str | None
) -> str | None:
    """Return the canonical string stored in the three columns, or None if empty."""
    if start is None or precision is None:
        return None
    return format_partial_date(start, precision)


def parse_iso_date(value: str) -> date:
    """Parse a strict calendar date ``YYYY-MM-DD``."""
    match = _DAY_RE.fullmatch(value)
    if not match:
        raise PartialDateError("expected YYYY-MM-DD")
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError as exc:
        raise PartialDateError("not a valid calendar date") from exc


def coerce_date(value: object) -> date:
    """Accept a ``date`` or an ISO ``YYYY-MM-DD`` string (YAML may yield either)."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_iso_date(value.strip())
    raise PartialDateError("expected a date")


def overlaps(start: date, end: date, range_from: date | None, range_to: date | None) -> bool:
    """True if [start, end] intersects [range_from, range_to] (open bounds allowed)."""
    return (range_to is None or start <= range_to) and (range_from is None or end >= range_from)


def within(start: date, end: date, range_from: date | None, range_to: date | None) -> bool:
    """True if [start, end] lies inside [range_from, range_to] (open bounds allowed)."""
    return (range_from is None or start >= range_from) and (range_to is None or end <= range_to)
