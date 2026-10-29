"""Partial dates, calendar dates and timestamps (DATA_MODEL §1.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from mdt.domain import clock
from mdt.domain.dates import (
    PartialDateError,
    coerce_date,
    format_partial_date,
    is_partial_date,
    overlaps,
    parse_iso_date,
    parse_partial_date,
    partial_date_from_columns,
    within,
)


@pytest.mark.parametrize(
    ("value", "start", "end", "precision"),
    [
        ("2020", "2020-01-01", "2020-12-31", "year"),
        ("2020-Q1", "2020-01-01", "2020-03-31", "quarter"),
        ("2020-Q2", "2020-04-01", "2020-06-30", "quarter"),
        ("2020-Q3", "2020-07-01", "2020-09-30", "quarter"),
        ("2020-Q4", "2020-10-01", "2020-12-31", "quarter"),
        ("2020-02", "2020-02-01", "2020-02-29", "month"),  # leap year
        ("2021-02", "2021-02-01", "2021-02-28", "month"),
        ("1900-02", "1900-02-01", "1900-02-28", "month"),  # 1900 is not a leap year
        ("2000-02", "2000-02-01", "2000-02-29", "month"),  # 2000 is
        ("2020-12", "2020-12-01", "2020-12-31", "month"),
        ("2020-02-29", "2020-02-29", "2020-02-29", "day"),
        ("1900-01-01", "1900-01-01", "1900-01-01", "day"),
        ("2100-12-31", "2100-12-31", "2100-12-31", "day"),
    ],
)
def test_valid_partial_dates(value: str, start: str, end: str, precision: str) -> None:
    parsed = parse_partial_date(value)
    assert (parsed.value, parsed.start_iso, parsed.end_iso, parsed.precision) == (
        value,
        start,
        end,
        precision,
    )
    assert format_partial_date(parsed.start, parsed.precision) == value
    assert partial_date_from_columns(parsed.start_iso, parsed.end_iso, precision) == value


@pytest.mark.parametrize(
    "value",
    [
        "2022-q1",  # lower-case q
        "2022-Q0",
        "2022-Q5",
        "2022-02-30",
        "2021-02-29",  # not a leap year
        "2022-13",
        "2022-00",
        "2022-1",
        "2022-01-1",
        "22",
        "1899",
        "2101",
        "1899-12-31",
        "2022/01/01",
        "2022-01-01T00:00",
        " 2022",
        "2022\n",
        "２０２２",  # full-width digits
        "٢٠٢٢-٠١",  # Arabic-Indic digits
        "",
    ],
)
def test_invalid_partial_dates(value: str) -> None:
    with pytest.raises(PartialDateError):
        parse_partial_date(value)
    assert not is_partial_date(value)


def test_partial_date_from_empty_columns() -> None:
    assert partial_date_from_columns(None, None, None) is None


def test_format_rejects_unknown_precision() -> None:
    with pytest.raises(PartialDateError):
        format_partial_date("2020-01-01", "week")


def test_parse_iso_date_is_strict() -> None:
    assert parse_iso_date("2024-02-29") == date(2024, 2, 29)
    for value in ("2023-02-29", "2024-2-29", "20240229", "２０２４-02-29"):
        with pytest.raises(PartialDateError):
            parse_iso_date(value)


def test_coerce_date_accepts_dates_and_iso_strings() -> None:
    assert coerce_date(date(2011, 7, 15)) == date(2011, 7, 15)
    assert coerce_date(" 2011-07-15 ") == date(2011, 7, 15)
    with pytest.raises(PartialDateError):
        coerce_date(20110715)


def test_interval_helpers_with_open_bounds() -> None:
    start, end = date(2020, 1, 1), date(2020, 12, 31)
    assert overlaps(start, end, date(2020, 12, 31), None)
    assert not overlaps(start, end, date(2021, 1, 1), None)
    assert overlaps(start, end, None, date(2020, 1, 1))
    assert not overlaps(start, end, None, date(2019, 12, 31))
    assert within(start, end, date(2020, 1, 1), date(2020, 12, 31))
    assert not within(start, end, date(2020, 1, 2), None)
    assert within(start, end, None, None)


def test_utc_now_has_the_storage_format() -> None:
    value = clock.utc_now()
    assert clock.is_timestamp(value)
    assert clock.parse_timestamp(value).tzinfo is UTC


def test_format_timestamp_requires_utc() -> None:
    assert clock.format_timestamp(datetime(2026, 1, 1, tzinfo=UTC)) == (
        "2026-01-01T00:00:00.000000Z"
    )
    with pytest.raises(ValueError, match="naive"):
        clock.format_timestamp(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-28T17:00:00.000000Z", "2026-10-28T17:00:00.000000Z"),
        ("2026-10-28T17:00Z", "2026-10-28T17:00:00.000000Z"),
        ("2026-10-28T17:00:00.5z", "2026-10-28T17:00:00.500000Z"),
        ("2026-10-28 19:00:00+02:00", "2026-10-28T17:00:00.000000Z"),
        ("2026-10-28T17:00:00.123456789Z", "2026-10-28T17:00:00.123456Z"),
    ],
)
def test_timestamp_input_is_normalised_to_utc(value: str, expected: str) -> None:
    assert clock.normalize_timestamp_input(value) == expected


@pytest.mark.parametrize(
    "value", ["2026-10-28T17:00:00", "2026-10-28", "yesterday", "2026-10-28T25:00:00Z"]
)
def test_timestamp_input_needs_a_zone_and_a_real_time(value: str) -> None:
    with pytest.raises(ValueError):
        clock.normalize_timestamp_input(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0999-06-01T00:00:00Z", "0999-06-01T00:00:00.000000Z"),
        ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000Z"),
        ("0100-06-01T12:00:00+00:00", "0100-06-01T12:00:00.000000Z"),
        ("1000-01-01T00:10:00+00:30", "0999-12-31T23:40:00.000000Z"),
        ("0202-06-01T10:00:00+03:00", "0202-06-01T07:00:00.000000Z"),
    ],
)
def test_timestamps_before_the_year_1000_keep_four_year_digits(value: str, expected: str) -> None:
    # strftime("%Y") writes "999" on glibc; the storage format needs "0999".
    result = clock.normalize_timestamp_input(value)
    assert result == expected
    assert clock.is_timestamp(result)


@pytest.mark.parametrize(
    "value",
    ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-01:00", "0000-01-01T00:00:00Z"],
)
def test_timestamps_outside_the_datetime_range_are_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        clock.normalize_timestamp_input(value)


def test_format_timestamp_pads_early_years() -> None:
    assert clock.format_timestamp(datetime(999, 1, 2, 3, 4, 5, 6, tzinfo=UTC)) == (
        "0999-01-02T03:04:05.000006Z"
    )


def test_timestamp_date_is_the_utc_calendar_date() -> None:
    assert clock.timestamp_date("2026-10-28T23:59:59.999999Z") == date(2026, 10, 28)
