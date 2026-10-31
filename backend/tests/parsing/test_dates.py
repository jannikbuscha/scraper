"""Month names and Kyiv time (parsing/dates.py, docs/COLLECTORS.md §7.5)."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from mdt.collectors.parsing.dates import (
    days_apart,
    find_posted_datetime,
    from_iso_offset,
    from_kyiv_local,
    kyiv_date_of_timestamp,
    kyiv_date_of_wayback_timestamp,
    month_number,
)
from mdt.collectors.parsing.texts import collapse_whitespace
from mdt.collectors.parsing.turbostream import find_route, loader_data
from tests.parsing.helpers import fixture_text


@pytest.mark.parametrize(
    ("name", "number"),
    [
        ("жовтня", 10),
        ("Жовтень", 10),
        ("жов.", 10),
        ("жовт.", 10),
        ("січня", 1),
        ("лютий", 2),
        ("лют.", 2),
        ("тра.", 5),
        ("вер.", 9),
        ("листопада", 11),
        ("лис.", 11),
        ("грудень", 12),
        ("September", 9),
        ("may", 5),
        ("Oct", 10),
        ("oct.", 10),
    ],
)
def test_month_names(name: str, number: int) -> None:
    assert month_number(name) == number


@pytest.mark.parametrize("name", ["", "жо.", "жов", "ж.", "mont", "ma.", "Juny", "13", "грудняя"])
def test_unknown_or_ambiguous_month_names_give_nothing(name: str) -> None:
    assert month_number(name) is None


def test_iso_offset_gives_utc_and_the_kyiv_date() -> None:
    result = from_iso_offset("2019-10-11T13:21:00+03:00")
    assert result is not None
    assert result.utc == "2019-10-11T10:21:00.000000Z"
    assert result.date == "2019-10-11"
    assert result.text == "2019-10-11T13:21:00+03:00"


def test_iso_offset_late_utc_evening_is_the_next_kyiv_day() -> None:
    result = from_iso_offset("2021-06-30T22:30:00Z")
    assert result is not None and result.date == "2021-07-01"


@pytest.mark.parametrize("value", ["2019-10-11T13:21:00", "2019-10-11", "11 жов. 2019", ""])
def test_iso_without_offset_gives_nothing(value: str) -> None:
    assert from_iso_offset(value) is None


def test_the_ministry_articles_use_publishedat_iso8601() -> None:
    for name in ("news_article_2019.html", "news_article_redirect_2021.html"):
        _, data = find_route(loader_data(fixture_text("ministry_news", name)), ("article",))
        published = data["article"]["publishedAt"]
        result = from_iso_offset(published["iso8601"])
        assert result is not None
        assert result.date == published["date"]


def test_kyiv_local_time_in_winter_and_summer() -> None:
    winter = from_kyiv_local(2021, 2, 17, 15, 38, text="t")
    summer = from_kyiv_local(2019, 9, 18, 15, 50, text="t")
    assert winter is not None and winter.utc == "2021-02-17T13:38:00.000000Z"
    assert summer is not None and summer.utc == "2019-09-18T12:50:00.000000Z"
    assert winter.warnings == () and summer.warnings == ()


def test_a_non_existent_local_time_keeps_the_date_without_utc() -> None:
    result = from_kyiv_local(2021, 3, 28, 3, 30, text="t")
    assert result is not None
    assert result.date == "2021-03-28"
    assert result.utc is None
    assert [code for code, _ in result.warnings] == ["ambiguous_time"]
    assert "does not exist" in result.warnings[0][1]


def test_an_ambiguous_local_time_keeps_the_date_without_utc() -> None:
    result = from_kyiv_local(2021, 10, 31, 3, 30, text="t")
    assert result is not None
    assert result.date == "2021-10-31"
    assert result.utc is None
    assert "exists twice" in result.warnings[0][1]


def test_times_next_to_the_transitions_convert() -> None:
    before_gap = from_kyiv_local(2021, 3, 28, 2, 59, text="t")
    after_fold = from_kyiv_local(2021, 10, 31, 4, 0, text="t")
    assert before_gap is not None and before_gap.utc == "2021-03-28T00:59:00.000000Z"
    assert after_fold is not None and after_fold.utc == "2021-10-31T02:00:00.000000Z"


def test_an_impossible_local_date_gives_nothing() -> None:
    assert from_kyiv_local(2021, 2, 30, 10, 0, text="t") is None


@pytest.mark.parametrize(
    "name",
    [
        "news_uk_2019_regulation.html",
        "news_uk_2019_komanda_duplicate_pair.html",
        "news_uk_2025_year_review.html",
        "news_en_2019_regulation.html",
        "news_en_2025_plans.html",
    ],
)
def test_posted_datetimes_of_the_kmu_pages(name: str) -> None:
    soup = BeautifulSoup(fixture_text("kmu_news", name), "html.parser")
    header = soup.select_one("div.page_title-desc")
    assert header is not None
    words = collapse_whitespace(header.get_text(" "))
    result = find_posted_datetime(header.get_text(" "))
    assert result is not None
    assert result.text in words
    assert result.text.startswith(("опубліковано", "posted"))
    assert result.utc is not None
    # The Kyiv date of the UTC value is the calendar date read from the page.
    assert kyiv_date_of_timestamp(result.utc) == result.date


def test_posted_datetime_values() -> None:
    uk = find_posted_datetime("Міністерство , опубліковано 05 жовтня 2020 року о 16:36")
    en = find_posted_datetime("Ministry, posted 18 September 2019 15:50")
    assert uk is not None and (uk.date, uk.utc) == ("2020-10-05", "2020-10-05T13:36:00.000000Z")
    assert uk.text == "опубліковано 05 жовтня 2020 року о 16:36"
    assert en is not None and (en.date, en.utc) == ("2019-09-18", "2019-09-18T12:50:00.000000Z")


@pytest.mark.parametrize(
    "text",
    [
        "опубліковано 05 жовтнября 2020 року о 16:36",
        "posted 31 February 2020 10:00",
        "опубліковано вчора",
        "",
    ],
)
def test_unreadable_posted_datetimes_give_nothing(text: str) -> None:
    assert find_posted_datetime(text) is None


def test_wayback_timestamps_and_day_distances() -> None:
    assert kyiv_date_of_wayback_timestamp("20191231223000") == "2020-01-01"
    assert kyiv_date_of_wayback_timestamp("20190101120000") == "2019-01-01"
    assert kyiv_date_of_wayback_timestamp("2019010112") is None
    assert kyiv_date_of_wayback_timestamp("20191301120000") is None
    assert days_apart("2019-10-11", "2019-10-12") == 1
    assert days_apart("2019-10-12", "2019-10-11") == 1
    assert days_apart("2019-10-11", "2019-10-11") == 0
