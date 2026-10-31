"""The polite HTTP client (docs/COLLECTORS.md §4, §12.3) on httpx2.MockTransport."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx2
import pytest

from mdt.collectors.client import (
    FetchResult,
    ListingHostUnavailable,
    RunCancelled,
    block_signature,
    parse_retry_after,
    user_agent,
)
from mdt.collectors.fetchlog import MemorySink
from tests.collectors.conftest import (
    TEST_UA,
    FakeClock,
    Site,
    fixture_path,
    make_client,
    make_config,
)

ROBOTS = "polite_client"


def robots(name: str, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, content=fixture_path(ROBOTS, name).read_bytes())


def outcomes(sink: MemorySink) -> list[tuple[str, str]]:
    return [(entry.url, entry.outcome) for entry in sink.fetches]


# --------------------------------------------------------------------------------------
# User-Agent and headers (§4.4)
# --------------------------------------------------------------------------------------


def test_user_agent_format() -> None:
    assert user_agent("someone@mdt-portfolio.internal").endswith(
        " (mailto:someone@mdt-portfolio.internal)"
    )
    assert user_agent("someone@mdt-portfolio.internal", "https://example.org/project").endswith(
        " (+https://example.org/project; mailto:someone@mdt-portfolio.internal)"
    )
    assert user_agent(None).startswith("MDT-Portfolio-Research/")
    assert user_agent(None).endswith("(replay)")


def test_requests_carry_our_headers_and_no_browser_imitation() -> None:
    site = Site({"https://example.org/page": "<html>Example</html>"})
    client = make_client(site)
    client.get("https://example.org/page")
    client.get("https://example.org/data.json", accept="application/json")
    robots_request, page, data = site.requests
    assert robots_request.headers["accept"] == "*/*"
    assert page.headers["user-agent"] == TEST_UA
    assert page.headers["accept"].startswith("text/html")
    assert page.headers["accept-encoding"] == "gzip, deflate"
    assert data.headers["accept"] == "application/json"
    for request in site.requests:
        assert "referer" not in request.headers
        assert request.headers["user-agent"] == TEST_UA


def test_cookies_are_kept_for_the_run_only() -> None:
    def set_cookie(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Set-Cookie": "visitor=1; Path=/"}, text="hi")

    site = Site({"https://example.org/a": set_cookie, "https://example.org/b": "b"})
    sink = MemorySink()
    client = make_client(site, sink=sink)
    first = client.get("https://example.org/a")
    client.get("https://example.org/b")
    assert site.requests[-1].headers.get("cookie") == "visitor=1"
    assert first.snapshot is not None and "set-cookie" not in first.snapshot.headers
    client.close()
    other = make_client(site)
    other.get("https://example.org/b")
    assert "cookie" not in site.requests[-1].headers


# --------------------------------------------------------------------------------------
# URLs and refusals (§4.1)
# --------------------------------------------------------------------------------------


def test_trailing_dot_hosts_default_ports_and_empty_paths_are_normalised() -> None:
    site = Site({"https://diia.gov.ua/services/RD4U": "ok", "https://example.org/": "root"})
    client = make_client(site)
    result = client.get("https://Diia.Gov.UA.:443/services/RD4U#top")
    assert result.ok and result.url == "https://diia.gov.ua/services/RD4U"
    assert client.get("https://example.org").ok
    assert "https://example.org/" in site.urls()


def test_excluded_hosts_trap_paths_and_invalid_urls_are_refused_without_a_request() -> None:
    site = Site()
    sink = MemorySink()
    client = make_client(site, sink=sink, config=make_config(exclude_hosts=["codeua.com"]))
    assert client.get("https://codeua.com/robots.txt").refusal == "excluded"
    assert client.get("https://example.org/cdn-cgi/l/email-protection").refusal == "trap"
    assert client.get("ftp://example.org/file").refusal == "invalid_url"
    assert site.requests == []
    assert [entry.outcome for entry in sink.fetches] == ["refused"] * 3
    assert [message[1] for message in sink.messages] == ["http_error"] * 3


# --------------------------------------------------------------------------------------
# robots.txt (§4.2)
# --------------------------------------------------------------------------------------


def test_robots_is_fetched_once_per_origin_and_disallowed_urls_are_not_requested() -> None:
    site = Site(
        {
            "https://osvita.diia.gov.ua/robots.txt": robots("robots_osvita_allow_first.txt"),
            "https://osvita.diia.gov.ua/courses": "courses",
        }
    )
    sink = MemorySink()
    client = make_client(site, sink=sink)
    assert client.get("https://osvita.diia.gov.ua/programmes").outcome == "robots_disallowed"
    assert client.get("https://osvita.diia.gov.ua/courses").ok
    assert site.urls() == [
        "https://osvita.diia.gov.ua/robots.txt",
        "https://osvita.diia.gov.ua/courses",
    ]
    assert sink.counts["robots_disallowed"] == 1
    assert ("https://osvita.diia.gov.ua/programmes", "robots_disallowed") in outcomes(sink)
    assert not any(code == "http_error" for _, code, _ in sink.messages)  # not partial


def test_robots_406_makes_the_host_unavailable() -> None:
    site = Site({"https://osvita.diia.gov.ua/robots.txt": robots("robots_osvita_406.txt", 406)})
    sink = MemorySink()
    client = make_client(site, sink=sink, listing_host=None)
    first = client.get("https://osvita.diia.gov.ua/courses")
    second = client.get("https://osvita.diia.gov.ua/other")
    assert first.refusal == second.refusal == "robots_unavailable"
    assert first.reason == "robots_unavailable"
    assert site.urls() == ["https://osvita.diia.gov.ua/robots.txt"]  # 406 is not retried
    codes = [code for _, code, _ in sink.messages]
    assert codes.count("robots_unavailable") == 1 and codes.count("http_error") == 2


def test_robots_unavailable_on_the_listing_host_fails_the_run() -> None:
    site = Site({"https://osvita.diia.gov.ua/robots.txt": robots("robots_osvita_406.txt", 406)})
    client = make_client(site)
    with pytest.raises(ListingHostUnavailable, match=r"osvita\.diia\.gov\.ua: robots\.txt"):
        client.get("https://osvita.diia.gov.ua/courses")


def test_group_less_rules_html_robots_and_rules_followed_by_html() -> None:
    site = Site(
        {
            "https://playcity.gov.ua/robots.txt": robots("robots_playcity_no_user_agent.txt"),
            "https://plan2.diia.gov.ua/robots.txt": robots("robots_plan2_html_200.html"),
            "https://usf.com.ua/robots.txt": robots("robots_usf_content_signal_with_html.txt"),
        }
    )
    client = make_client(site, listing_host=None)
    assert client.get("https://playcity.gov.ua/backend/x").outcome == "robots_disallowed"
    assert client.get("https://plan2.diia.gov.ua/anything").outcome == "http_error"  # 404 page
    assert client.get("https://usf.com.ua/").outcome == "http_error"
    assert "https://plan2.diia.gov.ua/anything" in site.urls()
    assert "https://usf.com.ua/" in site.urls()


def test_a_challenge_on_robots_blocks_the_host_without_retry() -> None:
    site = Site(
        {"https://codeua.com/robots.txt": robots("robots_codeua_cloudflare_challenge.html", 403)}
    )
    sink = MemorySink()
    client = make_client(site, sink=sink, listing_host=None)
    result = client.get("https://codeua.com/page")
    assert result.refusal == "blocked" and result.reason == "blocked"
    assert site.urls() == ["https://codeua.com/robots.txt"]
    blocked = [message for message in sink.messages if message[1] == "blocked"]
    assert len(blocked) == 1 and "Just a moment" in blocked[0][2]
    robots_rows = [entry for entry in sink.fetches if entry.purpose == "robots"]
    assert [entry.outcome for entry in robots_rows] == ["blocked"]
    assert len(sink.snapshots) == 1  # the challenge body is kept


def test_kmu_rules_also_apply_to_redirect_hops() -> None:
    site = Site(
        {
            "https://www.kmu.gov.ua/robots.txt": robots("robots_kmu.txt"),
            "https://www.kmu.gov.ua/news": httpx2.Response(302, headers={"Location": "/timeline"}),
        }
    )
    sink = MemorySink()
    client = make_client(site, sink=sink)
    assert client.get("https://www.kmu.gov.ua/npas/1").outcome == "robots_disallowed"
    result = client.get("https://www.kmu.gov.ua/news")
    assert result.outcome == "robots_disallowed"
    assert result.redirects == ("302 https://www.kmu.gov.ua/timeline",)
    assert "https://www.kmu.gov.ua/timeline" not in site.urls()
    assert outcomes(sink)[-2:] == [
        ("https://www.kmu.gov.ua/news", "redirect"),
        ("https://www.kmu.gov.ua/timeline", "robots_disallowed"),
    ]


def test_crawl_delay_raises_the_interval(clock: FakeClock) -> None:
    site = Site(
        {
            "https://data.gov.ua/robots.txt": robots("robots_data_gov_ua.txt"),
            "https://data.gov.ua/a": "a",
            "https://data.gov.ua/b": "b",
        }
    )
    client = make_client(site, clock=clock)
    client.get("https://data.gov.ua/a")
    client.get("https://data.gov.ua/b")
    # From the robots.txt request on, the host's interval is its Crawl-delay of 10 s.
    assert clock.sleeps == [10.0, 10.0]


def test_a_crawl_delay_above_max_wait_throttles_the_host(clock: FakeClock) -> None:
    body = b"User-agent: *\nCrawl-delay: 900\n"
    site = Site({"https://slow.example.org/robots.txt": body})
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock, listing_host=None)
    result = client.get("https://slow.example.org/page")
    assert result.refusal == "throttled" and result.reason == "throttled"
    assert [code for _, code, _ in sink.messages][:1] == ["throttled"]
    assert site.urls() == ["https://slow.example.org/robots.txt"]


# --------------------------------------------------------------------------------------
# Redirects (§4.5)
# --------------------------------------------------------------------------------------


def test_redirects_are_followed_hop_by_hop_with_relative_locations() -> None:
    site = Site(
        {
            "https://thedigital.gov.ua/news/old": httpx2.Response(
                302, headers={"Location": "/news/technologies/old"}
            ),
            "https://thedigital.gov.ua/news/technologies/old": httpx2.Response(
                301, headers={"Location": "https://www.example.org/final"}
            ),
            "https://www.example.org/final": "final page",
        }
    )
    sink = MemorySink()
    client = make_client(site, sink=sink)
    result = client.get("https://thedigital.gov.ua/news/old")
    assert result.ok and result.final_url == "https://www.example.org/final"
    assert result.redirects == (
        "302 https://thedigital.gov.ua/news/technologies/old",
        "301 https://www.example.org/final",
    )
    assert result.snapshot is not None
    assert result.snapshot.url == "https://thedigital.gov.ua/news/old"
    assert result.snapshot.final_url == "https://www.example.org/final"
    assert list(result.snapshot.redirects) == list(result.redirects)
    # The cross-host hop fetched the robots.txt of the new host first.
    assert site.urls().index("https://www.example.org/robots.txt") < site.urls().index(
        "https://www.example.org/final"
    )
    assert [entry.outcome for entry in sink.fetches if entry.purpose == "content"] == [
        "redirect",
        "redirect",
        "ok",
    ]


def test_at_most_five_redirects() -> None:
    routes = {
        f"https://example.org/r{n}": httpx2.Response(302, headers={"Location": f"/r{n + 1}"})
        for n in range(10)
    }
    site = Site(routes)
    sink = MemorySink()
    client = make_client(site, sink=sink)
    result = client.get("https://example.org/r0")
    assert result.outcome == "http_error" and "more than 5 redirects" in (result.error or "")
    assert len(result.redirects) == 5
    assert "https://example.org/r6" not in site.urls()


def test_a_redirect_to_an_excluded_host_is_refused() -> None:
    site = Site(
        {
            "https://example.org/go": httpx2.Response(
                302, headers={"Location": "https://codeua.com/"}
            )
        }
    )
    client = make_client(site, config=make_config(exclude_hosts=["codeua.com"]))
    result = client.get("https://example.org/go")
    assert result.outcome == "refused" and result.refusal == "excluded"
    assert not any("codeua.com" in url for url in site.urls())


# --------------------------------------------------------------------------------------
# Throttling (§4.3)
# --------------------------------------------------------------------------------------


def test_throttling_waits_from_end_to_start_per_host(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/1": "1", "https://a.example.org/2": "2"}, clock=clock)
    site.duration = 0.4  # each request takes 0.4 s
    site.routes["https://b.example.org/1"] = "b1"
    client = make_client(site, clock=clock)
    client.get("https://a.example.org/1")  # robots(a), then a/1 after 1 s
    clock.advance(0.3)
    client.get("https://a.example.org/2")  # 0.3 s passed since a/1 ended: waits 0.7 s
    client.get("https://b.example.org/1")  # another host: robots(b) at once, then 1 s
    assert clock.sleeps == [1.0, 0.7, 1.0]


def test_retries_and_robots_requests_count_for_the_interval(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/x": [503, "ok"]}, clock=clock)
    client = make_client(site, clock=clock, config=make_config(backoff_base_s=0.5))
    assert client.get("https://a.example.org/x").ok
    # robots → x: 1 s; then the backoff (0.5 s ± 20 %) and the rest of the 1 s interval.
    backoff = clock.sleeps[1]
    assert clock.sleeps[0] == 1.0 and 0.4 <= backoff <= 0.6
    assert clock.sleeps[2] == pytest.approx(1.0 - backoff)


def test_a_cancel_interrupts_the_interval_wait(clock: FakeClock) -> None:
    cancel = threading.Event()
    site = Site({"https://a.example.org/1": "1"})
    client = make_client(site, clock=clock, cancel=cancel)
    clock.on_sleep = lambda _seconds: cancel.set()
    with pytest.raises(RunCancelled):
        client.get("https://a.example.org/1")
    assert site.urls() == ["https://a.example.org/robots.txt"]
    with pytest.raises(RunCancelled):  # and before every further request
        client.get("https://a.example.org/1")


def test_replay_mode_never_waits(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/1": [503, "1"]})
    client = make_client(site, clock=clock, replay=True)
    assert client.get("https://a.example.org/1").ok
    assert clock.sleeps == []


# --------------------------------------------------------------------------------------
# Retries and backoff (§4.6)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_retryable_statuses_are_retried_twice(status: int, clock: FakeClock) -> None:
    site = Site({"https://a.example.org/x": status})
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock, listing_host=None)
    result = client.get("https://a.example.org/x")
    assert result.outcome == "http_error" and result.status == status
    rows = [entry for entry in sink.fetches if entry.purpose == "content"]
    assert [entry.attempt for entry in rows] == [1, 2, 3]
    assert rows[-1].raw_snapshot_id is not None  # only the final response body is kept
    assert rows[0].raw_snapshot_id is None
    # After the robots interval (1 s), the backoff waits; they exceed the interval.
    backoffs = clock.sleeps[1:]
    assert len(backoffs) == 2
    assert 4.0 <= backoffs[0] <= 6.0 and 8.0 <= backoffs[1] <= 12.0


@pytest.mark.parametrize("status", [500, 404, 400])
def test_other_errors_are_not_retried(status: int) -> None:
    site = Site({"https://a.example.org/x": status})
    sink = MemorySink()
    client = make_client(site, sink=sink)
    result = client.get("https://a.example.org/x")
    assert result.outcome == "http_error" and result.snapshot is not None
    assert site.urls().count("https://a.example.org/x") == 1
    assert [code for _, code, _ in sink.messages] == ["http_error"]


def test_network_errors_are_retried_then_reported(clock: FakeClock) -> None:
    calls: list[int] = []

    def flaky(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        if len(calls) < 3:
            raise httpx2.ConnectError("connection reset", request=request)
        return httpx2.Response(200, text="finally")

    site = Site({"https://a.example.org/x": flaky})
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock)
    assert client.get("https://a.example.org/x").ok
    rows = [entry.outcome for entry in sink.fetches if entry.purpose == "content"]
    assert rows == ["network_error", "network_error", "ok"]

    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("read timed out", request=request)

    site.routes["https://a.example.org/y"] = broken
    failed = client.get("https://a.example.org/y")
    assert failed.outcome == "network_error" and failed.reason == "network_error"
    assert "ReadTimeout" in (failed.error or "")


def test_retry_after_in_seconds_and_as_http_date(clock: FakeClock) -> None:
    answers: list[int] = []

    def dated(request: httpx2.Request) -> httpx2.Response:
        answers.append(1)
        if len(answers) > 1:
            return httpx2.Response(200, text="ok")
        moment = datetime.fromtimestamp(clock.time() + 30, tz=UTC)
        return httpx2.Response(503, headers={"Retry-After": format_datetime(moment, usegmt=True)})

    site = Site(
        {
            "https://a.example.org/s": [
                httpx2.Response(429, headers={"Retry-After": "7"}, text="slow down"),
                "ok",
            ],
            "https://a.example.org/d": dated,
        }
    )
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock)
    assert client.get("https://a.example.org/s").ok
    assert client.get("https://a.example.org/d").ok
    assert 7.0 in clock.sleeps
    assert any(abs(wait - 30.0) < 1.5 for wait in clock.sleeps)
    retried = [entry for entry in sink.fetches if entry.retry_after_s is not None]
    assert [round(entry.retry_after_s or 0) for entry in retried] == [7, 30]


def test_a_retry_after_above_max_wait_throttles_the_host(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/x": httpx2.Response(429, headers={"Retry-After": "3600"})})
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock, listing_host=None)
    result = client.get("https://a.example.org/x")
    assert result.outcome == "http_error" and result.throttled and result.retry_after_s == 3600
    assert result.reason == "throttled"
    assert 3600.0 not in clock.sleeps
    assert client.get("https://a.example.org/other").refusal == "throttled"
    assert "throttled" in [code for _, code, _ in sink.messages]


def test_throttling_of_the_listing_host_fails_the_run(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/x": httpx2.Response(503, headers={"Retry-After": "601"})})
    client = make_client(site, clock=clock)
    with pytest.raises(ListingHostUnavailable, match=r"a\.example\.org: throttled"):
        client.get("https://a.example.org/x")


def test_after_the_listing_is_complete_a_blocked_listing_host_is_no_longer_fatal() -> None:
    site = Site({"https://a.example.org/x": 403})
    client = make_client(site)
    client.listing_done()
    for _ in range(3):
        client.get("https://a.example.org/x")
    assert client.get("https://a.example.org/x").refusal == "blocked"


def test_the_budget_of_a_manual_fetch(clock: FakeClock) -> None:
    site = Site({"https://a.example.org/x": httpx2.Response(503, headers={"Retry-After": "90"})})
    client = make_client(site, clock=clock, budget_s=60, listing_host=None)
    result = client.get("https://a.example.org/x")
    assert result.out_of_budget and result.reason == "throttled"
    assert 90.0 not in clock.sleeps


def test_parse_retry_after() -> None:
    now = 1_800_000_000.0
    assert parse_retry_after("120", now) == 120.0
    assert parse_retry_after(" 1.5 ", now) == 1.5
    assert parse_retry_after("Thu, 01 Jan 1970 00:00:00 GMT", now) == 0.0
    assert parse_retry_after("soon", now) is None
    assert parse_retry_after(None, now) is None


# --------------------------------------------------------------------------------------
# Size limit (§4.4) and block detection (§4.7)
# --------------------------------------------------------------------------------------


def test_size_limit_by_content_length_and_by_the_body() -> None:
    big = b"x" * 2048

    def declared(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Length": "999999"}, content=b"short")

    def streamed(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=iter([big[:1024], big[1024:]]))

    site = Site(
        {"https://a.example.org/declared": declared, "https://a.example.org/body": streamed}
    )
    sink = MemorySink()
    client = make_client(site, sink=sink, config=make_config(max_bytes=1500))
    for path in ("declared", "body"):
        result = client.get(f"https://a.example.org/{path}")
        assert result.outcome == "too_large" and result.snapshot is None
        assert result.reason == "too_large"
    assert sink.snapshots == {}


@pytest.mark.parametrize(
    ("status", "headers", "body", "signature"),
    [
        (403, {}, b"<html><title>Just a moment...</title></html>", "Just a moment"),
        (503, {}, b"<script>window._cf_chl_opt={cType: 'managed'}</script>", "managed"),
        (403, {"cf-mitigated": "challenge"}, b"", "cf-mitigated"),
        (403, {}, b"<html><title>Access Denied</title>Reference #18</html>", "Access Denied"),
    ],
)
def test_block_signatures(
    status: int, headers: dict[str, str], body: bytes, signature: str
) -> None:
    assert signature in (block_signature(status, headers, body) or "")
    assert block_signature(200, {}, b"<title>Example</title>") is None
    assert block_signature(404, {}, b"Access Denied") is None  # Akamai answers 403


def test_the_codeua_challenge_page_blocks_the_host() -> None:
    page = fixture_path(ROBOTS, "robots_codeua_cloudflare_challenge.html").read_bytes()
    site = Site({"https://challenge.example.org/page": httpx2.Response(403, content=page)})
    sink = MemorySink()
    client = make_client(site, sink=sink)
    with pytest.raises(ListingHostUnavailable, match="blocked"):
        client.get("https://challenge.example.org/page")
    assert sink.fetches[-1].outcome == "blocked"
    assert [code for _, code, _ in sink.messages] == ["blocked"]


def test_three_consecutive_403_block_the_host() -> None:
    site = Site({"https://a.example.org/x": 403, "https://a.example.org/ok": "fine"})
    sink = MemorySink()
    client = make_client(site, sink=sink, listing_host=None)
    first = [client.get("https://a.example.org/x").outcome for _ in range(2)]
    assert first == ["http_error", "http_error"]
    assert client.get("https://a.example.org/ok").ok  # resets the streak
    results = [client.get("https://a.example.org/x").outcome for _ in range(3)]
    assert results == ["http_error", "http_error", "blocked"]
    assert client.get("https://a.example.org/ok").refusal == "blocked"


def test_wayback_429_page_after_the_retries(clock: FakeClock) -> None:
    page = fixture_path("wayback", "availability_429.html").read_bytes()
    url = "https://archive.org/wayback/available?url=example.org&timestamp=20191231"
    site = Site({url: httpx2.Response(429, content=page)})
    sink = MemorySink()
    client = make_client(site, sink=sink, clock=clock, listing_host=None)
    result = client.get(url)
    assert result.outcome == "http_error" and result.status == 429
    assert result.snapshot is not None and result.snapshot.body == page
    assert len([entry for entry in sink.fetches if entry.purpose == "content"]) == 3


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------


def test_fetch_result_reasons() -> None:
    def reason(**kwargs: object) -> str:
        return FetchResult(url="https://example.org/", **kwargs).reason  # type: ignore[arg-type]

    assert reason(outcome="robots_disallowed") == "robots_disallowed"
    assert reason(outcome="refused", refusal="robots_unavailable") == "robots_unavailable"
    assert reason(outcome="refused", refusal="excluded") == "blocked"
    assert reason(outcome="refused", refusal="throttled") == "throttled"
    assert reason(outcome="refused", refusal="no_fixture") == "http_error"
    assert reason(outcome="http_error") == "http_error"
    assert FetchResult(url="x", outcome="not_modified").ok
