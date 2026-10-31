"""robots.txt interpretation (docs/COLLECTORS.md §4.2) on the Phase 0b fixtures."""

from __future__ import annotations

import pytest

from mdt.collectors.robots import PRODUCT_TOKEN, RobotsPolicy, policy_from_response, preprocess
from tests.collectors.conftest import fixture_path


def policy(name: str, status: int = 200) -> RobotsPolicy:
    return policy_from_response(status, fixture_path("polite_client", name).read_bytes())


def test_longest_match_beats_a_leading_allow() -> None:
    rules = policy("robots_osvita_allow_first.txt")
    assert rules.state == "rules"
    assert not rules.allows("https://osvita.diia.gov.ua/programmes")
    assert not rules.allows("https://osvita.diia.gov.ua/search?q=x")
    assert rules.allows("https://osvita.diia.gov.ua/courses/example")


def test_rules_without_a_user_agent_line_are_honoured() -> None:
    rules = policy("robots_playcity_no_user_agent.txt")
    assert rules.state == "rules"
    assert not rules.allows("https://playcity.gov.ua/backend/")
    assert not rules.allows("https://playcity.gov.ua/news?sort=date")
    assert rules.allows("https://playcity.gov.ua/modules/site.css")  # longer Allow wins
    assert rules.allows("https://playcity.gov.ua/")


def test_an_html_page_as_robots_txt_allows_all() -> None:
    page = policy("robots_plan2_html_200.html")
    assert page.state == "allow_all"
    assert page.allows("https://plan2.diia.gov.ua/anything")


def test_rules_followed_by_html_are_read_and_the_html_ignored() -> None:
    rules = policy("robots_usf_content_signal_with_html.txt")
    assert rules.state == "rules"
    assert rules.allows("https://usf.com.ua/")
    body = fixture_path("polite_client", "robots_usf_content_signal_with_html.txt").read_bytes()
    text = preprocess(body)
    assert text is not None and "<html" not in text and "DOCTYPE" not in text


def test_kmu_rules_and_groups() -> None:
    rules = policy("robots_kmu.txt")
    for path in ("/npas/123", "/timeline", "/storage/file.pdf", "/api/x"):
        assert not rules.allows(f"https://www.kmu.gov.ua{path}"), path
    assert rules.allows("https://www.kmu.gov.ua/news/example")
    # Crawl-delay and Request-rate belong to another group (docs/SOURCES.md S4b).
    assert rules.crawl_delay() is None and rules.request_interval() is None


def test_crawl_delay_of_our_group() -> None:
    rules = policy("robots_data_gov_ua.txt")
    assert rules.crawl_delay() == 10.0
    assert not rules.allows("https://data.gov.ua/api/3/action/package_list")
    assert rules.allows("https://data.gov.ua/dataset/example")


def test_request_rate_and_our_product_token() -> None:
    body = (
        f"User-agent: *\nDisallow: /\n\nUser-agent: {PRODUCT_TOKEN}\nDisallow: /private\n"
        "Request-rate: 1/5s\n"
    ).encode()
    rules = policy_from_response(200, body)
    assert rules.allows("https://example.org/page")  # our group, not "*"
    assert not rules.allows("https://example.org/private/x")
    assert rules.request_interval() == 5.0


def test_bom_and_lenient_lines() -> None:
    text = preprocess(b"\xef\xbb\xbfUser-agent: *\nDisallow /blocked\nDisallow: /real\n")
    assert text is not None
    assert "Disallow /blocked" not in text  # not "field: value": dropped
    rules = policy_from_response(200, b"\xef\xbb\xbfUser-agent: *\nDisallow /a\nDisallow: /b\n")
    assert rules.allows("https://example.org/a") and not rules.allows("https://example.org/b")


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (404, "allow_all"),
        (410, "allow_all"),
        (401, "blocked"),
        (403, "blocked"),
        (429, "blocked"),
        (400, "unavailable"),
        (406, "unavailable"),
        (500, "unavailable"),
        (503, "unavailable"),
        (None, "unavailable"),
    ],
)
def test_statuses(status: int | None, state: str) -> None:
    result = policy_from_response(status, b"")
    assert result.state == state
    assert result.allows("https://example.org/") == (state == "allow_all")


def test_406_from_the_fixture_is_unavailable_and_a_challenge_blocks() -> None:
    assert policy("robots_osvita_406.txt", 406).state == "unavailable"
    challenged = policy_from_response(
        403,
        fixture_path("polite_client", "robots_codeua_cloudflare_challenge.html").read_bytes(),
        challenge=True,
    )
    assert challenged.state == "blocked" and "challenge" in challenged.reason
