# ruff: noqa: RUF001, RUF002, RUF003
"""Dates of source pages (docs/COLLECTORS.md §7.5; C4, C4b).

* **Month names:** Ukrainian genitive (``жовтня``), nominative (``жовтень``) and
  abbreviated forms (a prefix of at least three letters with a dot, ``жов.``, ``жовт.``),
  and English month names (full or three letters). Unknown or ambiguous input gives no
  month, so never a guessed date.
* **Time zones:** an ISO 8601 timestamp with an offset gives the UTC timestamp and the
  Europe/Kyiv calendar date. Kyiv local time without a zone (www.kmu.gov.ua) is converted
  with ``zoneinfo``; a local time that does not exist or exists twice (DST changes) gives
  no UTC value, only the warning ``ambiguous_time``, and keeps the calendar date.
* **No dates from titles:** nothing here looks at titles (a "від <date>" in a document
  title dates the act it cites, SOURCES S4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.domain.clock import format_timestamp, normalize_timestamp_input, parse_timestamp

KYIV = ZoneInfo("Europe/Kyiv")

UKRAINIAN_MONTHS_NOMINATIVE = (
    "січень",
    "лютий",
    "березень",
    "квітень",
    "травень",
    "червень",
    "липень",
    "серпень",
    "вересень",
    "жовтень",
    "листопад",
    "грудень",
)
UKRAINIAN_MONTHS_GENITIVE = (
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)
ENGLISH_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MIN_ABBREVIATION = 3

#: ``опубліковано 11 жовтня 2019 року о 17:48`` (www.kmu.gov.ua, Ukrainian pages).
_UKRAINIAN_POSTED = re.compile(
    r"опубліковано\s+(?P<day>\d{1,2})\s+(?P<month>[^\W\d_]+)\s+(?P<year>\d{4})\s+року\s+о\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)
#: ``posted 18 September 2019 15:50`` (www.kmu.gov.ua, English pages).
_ENGLISH_POSTED = re.compile(
    r"posted\s+(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+\.?)\s+(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceDate:
    """A date read from a source: the Europe/Kyiv calendar date, the UTC timestamp when
    the time is unambiguous, the date words as written, and warnings
    (``(code, message)`` pairs)."""

    date: str
    utc: str | None
    text: str
    warnings: tuple[tuple[str, str], ...] = ()


def month_number(name: str) -> int | None:
    """1-12 for a Ukrainian or English month name, else None (unknown or ambiguous)."""
    word = name.strip().casefold()
    if not word:
        return None
    for months in (UKRAINIAN_MONTHS_GENITIVE, UKRAINIAN_MONTHS_NOMINATIVE, ENGLISH_MONTHS):
        if word in months:
            return months.index(word) + 1
    stem = word.removesuffix(".")
    if len(stem) < _MIN_ABBREVIATION or not stem.isalpha():
        return None
    matches = {
        index + 1
        for months in (UKRAINIAN_MONTHS_GENITIVE, UKRAINIAN_MONTHS_NOMINATIVE, ENGLISH_MONTHS)
        for index, month in enumerate(months)
        if month.startswith(stem)
    }
    if len(matches) != 1:
        return None
    if word.endswith(".") or stem in {month[:3] for month in ENGLISH_MONTHS}:
        return matches.pop()
    return None


def from_iso_offset(value: str) -> SourceDate | None:
    """An ISO 8601 timestamp with an explicit offset → UTC and the Kyiv calendar date;
    ``text`` is the value as given. Naive or malformed values give None."""
    try:
        utc = normalize_timestamp_input(value.strip())
    except ValueError:
        return None
    local = parse_timestamp(utc).astimezone(KYIV)
    return SourceDate(date=local.date().isoformat(), utc=utc, text=value)


def from_kyiv_local(
    year: int, month: int, day: int, hour: int, minute: int, *, text: str
) -> SourceDate | None:
    """Kyiv wall-clock time → UTC. A time that does not exist (spring forward) or exists
    twice (fall back) keeps the calendar date and gives no UTC value, with the warning
    ``ambiguous_time``. An impossible date or time gives None."""
    try:
        naive = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    calendar_date = naive.date().isoformat()
    early = naive.replace(tzinfo=KYIV, fold=0)
    late = naive.replace(tzinfo=KYIV, fold=1)
    early_utc, late_utc = early.astimezone(UTC), late.astimezone(UTC)
    exists = early_utc.astimezone(KYIV).replace(tzinfo=None) == naive
    if early_utc != late_utc or not exists:
        kind = "exists twice" if exists else "does not exist"
        warning = ("ambiguous_time", f"the Kyiv local time {naive:%Y-%m-%d %H:%M} {kind}")
        return SourceDate(date=calendar_date, utc=None, text=text, warnings=(warning,))
    return SourceDate(date=calendar_date, utc=format_timestamp(early_utc), text=text)


def find_posted_datetime(text: str) -> SourceDate | None:
    """The publication time of a www.kmu.gov.ua page in its header text: ``опубліковано
    DD <month genitive> YYYY року о HH:MM`` or ``posted D Month YYYY HH:MM``, matched after
    collapsing whitespace, as Kyiv local time. ``text`` of the result = the date words as
    on the page (after collapsing). None if neither form is present or the date is
    invalid."""
    collapsed = collapse_whitespace(text)
    for pattern in (_UKRAINIAN_POSTED, _ENGLISH_POSTED):
        match = pattern.search(collapsed)
        if match is None:
            continue
        month = month_number(match.group("month"))
        if month is None:
            return None
        return from_kyiv_local(
            int(match.group("year")),
            month,
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            text=match.group(0),
        )
    return None


def kyiv_date_of_timestamp(value: str) -> str:
    """The Europe/Kyiv calendar date of a storage-format UTC timestamp."""
    return parse_timestamp(value).astimezone(KYIV).date().isoformat()


def kyiv_date_of_wayback_timestamp(timestamp: str) -> str | None:
    """The Kyiv calendar date of a 14-digit UTC Wayback timestamp (``YYYYMMDDhhmmss``),
    or None when it is not one (C5, docs/DATA_MODEL.md §15.12)."""
    if not re.fullmatch(r"\d{14}", timestamp):
        return None
    try:
        moment = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return moment.astimezone(KYIV).date().isoformat()


def days_apart(left: str, right: str) -> int:
    """Absolute distance in days between two ``YYYY-MM-DD`` dates."""
    return abs((date.fromisoformat(left) - date.fromisoformat(right)) // timedelta(days=1))
