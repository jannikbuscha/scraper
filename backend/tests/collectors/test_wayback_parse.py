"""C5 ``wayback``: the CDX parser, the queries and the mapping of captures to subjects
(docs/COLLECTORS.md §8.5, §12.2), on the synthetic fixtures of
``backend/tests/fixtures/wayback/`` (no database, no network).

Every value asserted here is synthetic (reserved example hosts, made-up timestamps); none of
it describes the Wayback Machine's holdings for a real site.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace

import pytest

from mdt.collectors.base import Snapshot
from mdt.collectors.parsing import ParseError
from mdt.collectors.sources import load_sources
from mdt.collectors.wayback import (
    COLLECTOR,
    RUBRICS,
    CdxPage,
    SubjectIndex,
    SubjectUrl,
    archive_capture_url,
    capture_of,
    covered,
    earliest_by_key,
    parse_cdx_json,
    prefix_query,
    query_target,
    single_urls,
    subject_urls,
    url_form,
    url_query,
)
from mdt.config import REPO_ROOT
from mdt.domain.reconcile import archive_key
from tests.collectors.conftest import FIXTURES
from tests.collectors.thedigital_helpers import fixture_meta, fixture_snapshot
from tests.collectors.wayback_helpers import PROJECTS, SERVICES, TEST_PREFIX

RESUME_KEY = "org%2Cexample%29%2Fprojects%2Fexample-beta+20160704000000%21"
HEADER = ["urlkey", "timestamp", "original", "statuscode", "mimetype"]


def snapshot(name: str) -> Snapshot:
    return fixture_snapshot("wayback", name)


def body_snapshot(data: object, *, raw: bytes | None = None) -> Snapshot:
    """A synthetic CDX response (a JSON value or raw bytes)."""
    base = snapshot("synthetic_cdx_exact_limit1")
    body = raw if raw is not None else json.dumps(data).encode()
    return replace(base, body=body, size=len(body))


def row(urlkey: str, timestamp: str, original: str, status: str = "200") -> list[str]:
    return [urlkey, timestamp, original, status, "text/html"]


# --------------------------------------------------------------------------------------
# The parser on the synthetic fixtures
# --------------------------------------------------------------------------------------


def test_the_first_prefix_page_ends_with_a_resume_key() -> None:
    page = parse_cdx_json(snapshot("synthetic_cdx_resume_key"))
    assert page.resume_key == RESUME_KEY
    assert [(item.urlkey, item.timestamp) for item in page.rows] == [
        ("org,example)/projects/business", "20170101000000"),
        ("org,example)/projects/business/example-beta", "20210301223000"),
    ]
    assert page.warnings == ()


def test_the_collapsed_prefix_page_keeps_every_row_in_order() -> None:
    page = parse_cdx_json(snapshot("synthetic_cdx_prefix_collapse"))
    assert page.resume_key is None
    assert [item.urlkey.removeprefix("org,example)") for item in page.rows] == [
        "/projects/example-beta",
        "/projects/page/2",
        "/projects/regions/example-alpha",
        "/projects/technologies/example-alpha",
        "/projects/technologies/example-alpha",
        "/projects/technologies/example-gamma",
    ]
    first = page.rows[0]
    assert first.original == "http://example.org/projects/example-beta"
    assert first.values == (
        "org,example)/projects/example-beta",
        "20160704000000",
        "http://example.org/projects/example-beta",
        "200",
        "text/html",
    )


def test_two_rows_of_one_url_in_reverse_order_give_the_earliest() -> None:
    page = parse_cdx_json(snapshot("synthetic_cdx_prefix_collapse"))
    found = earliest_by_key([(page, snapshot("synthetic_cdx_prefix_collapse"))])
    capture = found["example.org/projects/technologies/example-alpha"]
    assert capture.timestamp == "20180510000000"
    assert capture.original == "http://www.example.org/projects/technologies/example-alpha/"


@pytest.mark.parametrize("name", ["synthetic_cdx_empty", "synthetic_cdx_header_only"])
def test_no_captures(name: str) -> None:
    assert parse_cdx_json(snapshot(name)) == CdxPage()


def test_a_single_url_query_gives_its_one_row() -> None:
    page = parse_cdx_json(snapshot("synthetic_cdx_exact_limit1"))
    assert [(item.urlkey, item.timestamp, item.original) for item in page.rows] == [
        ("com,example)/", "20150101000000", "http://example.com/")
    ]


def test_columns_are_located_by_name_and_further_columns_ignored() -> None:
    page = parse_cdx_json(snapshot("synthetic_cdx_extra_columns"))
    (item,) = page.rows
    assert (item.urlkey, item.timestamp, item.original) == (
        "org,example)/services/example-one",
        "20190405060708",
        "https://example.org/services/example-one",
    )
    assert len(item.values) == 7  # the row as listed, the evidence quote


def test_a_gzip_body_without_content_encoding_is_decompressed() -> None:
    gzipped = snapshot("synthetic_cdx_gzipped")
    assert gzipped.body[:2] == b"\x1f\x8b"
    assert "content-encoding" not in gzipped.headers
    (item,) = parse_cdx_json(gzipped).rows
    assert (item.timestamp, item.original) == (
        "20191231230000",
        "https://example.org/services/example-two",
    )


def test_a_status_other_than_200_is_skipped_with_a_warning() -> None:
    page = parse_cdx_json(
        body_snapshot(
            [
                HEADER,
                row("org,example)/a", "20200101000000", "http://example.org/a", "404"),
                row("org,example)/b", "20200101000000", "http://example.org/b"),
            ]
        )
    )
    assert [item.urlkey for item in page.rows] == ["org,example)/b"]
    assert [code for code, _ in page.warnings] == ["invalid_value"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"rows": []}, "not an array of rows"),
        ([HEADER, "not a row"], "not an array of rows"),
        ([[1, 2, 3]], "field names"),
        ([[]], "field names"),
        ([["urlkey", "original"]], "lacks the columns timestamp"),
        ([HEADER, ["org,example)/", "20200101000000"]], "has 2 values"),
        ([HEADER, row("org,example)/", "2020010100000", "http://example.org/")], "14-digit"),
        ([HEADER, row("org,example)/", "20201340000000", "http://example.org/")], "14-digit"),
        ([HEADER, row("org,example)/", "20200101000000", "")], "no original URL"),
        ([HEADER, row("org,example)/", "20200101000000", "http://example.org/"), []], "values"),
        ([HEADER, [], [7]], "resume key"),
        ([HEADER, [], [""]], "resume key"),
    ],
)
def test_unexpected_structures_raise_parse_errors(data: object, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_cdx_json(body_snapshot(data))


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"<html><title>Not JSON</title></html>", "not JSON"),
        (b"\x1f\x8bnot really gzip", "cannot be decompressed"),
        (gzip.compress(b"\xff\xfe not utf-8"), "not JSON"),
    ],
)
def test_bodies_that_are_no_cdx_json_raise_parse_errors(raw: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_cdx_json(body_snapshot(None, raw=raw))


# --------------------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------------------


def synthetic_urls() -> list[SubjectUrl]:
    """The URLs of the synthetic subjects of the C5 test setup (fake IDs)."""
    projects = [{"id": f"prj_{slug}", **values} for slug, values in PROJECTS.items()]
    services = [
        {"id": f"svc_{index}", "urls": urls} for index, urls in enumerate(SERVICES.values())
    ]
    return subject_urls(projects, services, ())


def test_each_synthetic_cdx_fixture_is_a_query_c5_builds_for_the_test_setup() -> None:
    built = {prefix_query(TEST_PREFIX, 5000), prefix_query(TEST_PREFIX, 5000, RESUME_KEY)}
    built |= {single.query for single in single_urls(synthetic_urls(), [TEST_PREFIX])}
    fixtures = {
        fixture_meta("wayback", path.name.removesuffix(".meta.json"))["url"]
        for path in (FIXTURES / "wayback").glob("synthetic_cdx_*.meta.json")
    }
    assert fixtures == built


def test_the_capture_list_names_queries_c5_builds() -> None:
    """The real fixtures of ``mdt fixtures capture wayback`` replay C5's own requests."""
    config = load_sources(REPO_ROOT / "sources.yaml").collectors["wayback"]
    captures = {fixture.name: fixture.url for fixture in config.fixtures}
    assert captures["robots_web_archive"] == "https://web.archive.org/robots.txt"
    assert captures["cdx_prefix_projects_collapse"] == prefix_query(
        "thedigital.gov.ua/projects/", 50
    )
    assert captures["cdx_resume_key_news"] == prefix_query("thedigital.gov.ua/news/", 5)
    assert captures["cdx_exact_diia_services_earliest"] == url_query("https://diia.gov.ua/services")
    assert captures["cdx_no_captures"] == url_query(
        "https://thedigital.gov.ua/projects/mdt-portfolio-fixture-no-such-page"
    )
    assert config.options["prefixes"] == [
        "thedigital.gov.ua/projects/",
        "diia.gov.ua/services/",
        "diia.gov.ua./services/",
    ]


def test_the_prefix_query_uses_the_documented_parameters_in_order() -> None:
    assert prefix_query("example.org/projects/", 50) == (
        "https://web.archive.org/cdx/search/cdx?url=example.org/projects/&matchType=prefix"
        "&collapse=urlkey&output=json&fl=urlkey,timestamp,original,statuscode,mimetype"
        "&filter=statuscode:200&limit=50&showResumeKey=true"
    )
    assert prefix_query("example.org./projects/", 50).startswith(
        "https://web.archive.org/cdx/search/cdx?url=example.org./projects/&"
    )


def test_a_resume_key_is_passed_back_unchanged() -> None:
    assert prefix_query(TEST_PREFIX, 5000, RESUME_KEY).endswith(f"&resumeKey={RESUME_KEY}")
    # A raw key is escaped only where it would end the parameter.
    assert prefix_query(TEST_PREFIX, 5, "a&b c").endswith("&resumeKey=a%26b%20c")


def test_the_single_url_query_names_the_url_without_scheme_query_and_fragment() -> None:
    assert url_query("https://example.org/services/example-one?x=1#top") == (
        "https://web.archive.org/cdx/search/cdx?url=example.org/services/example-one"
        "&output=json&fl=urlkey,timestamp,original,statuscode,mimetype"
        "&filter=statuscode:200&limit=1"
    )
    assert query_target("https://EXAMPLE.org.") == "example.org/"
    assert query_target("http://example.org:8080/a/") == "example.org:8080/a/"
    assert query_target("https://example.org:443/a") == "example.org/a"


def test_characters_outside_the_safe_set_are_percent_encoded() -> None:
    assert "url=example.org/%D0%BF%D1%80%D0%BE&" in url_query("https://example.org/про")
    assert "url=example.org/a%2Bb&" in url_query("https://example.org/a+b")


def test_coverage_follows_the_cdx_prefix() -> None:
    prefixes = ["example.org/projects/"]
    assert covered("https://example.org/projects/technologies/example-alpha", prefixes)
    assert covered("https://www.example.org/Projects/x", prefixes)
    assert covered("https://example.org/projects/", prefixes)
    assert not covered("https://example.org/projects", prefixes)
    assert not covered("https://example.org/projectsx/a", prefixes)
    assert covered("https://example.org/projects/x", ["example.org./projects/"])
    assert covered("https://example.org/", ["example.org"])
    assert not covered("https://example.org.example.com/", ["example.org"])
    assert url_form("example.org") == "example.org/"
    assert url_form("http://www.example.org:80/A?b=1") == "example.org/a"
    assert url_form("https://example.org:8443/a") == "example.org:8443/a"


def test_single_urls_skip_covered_urls_and_query_each_archive_key_once() -> None:
    urls = [
        SubjectUrl("svc_1", "https://www.example.org/a/", "example.org/a", True),
        SubjectUrl("prj_1", "https://example.org/a", "example.org/a", False),
        SubjectUrl("prj_2", "https://example.org/projects/x", "example.org/projects/x", True),
    ]
    singles = single_urls(urls, ["example.org/projects/"])
    assert [(single.key, single.url) for single in singles] == [
        ("example.org/a", "https://example.org/a")
    ]


def test_subject_urls_skip_excluded_hosts_and_invalid_urls() -> None:
    projects = [
        {
            "id": "prj_1",
            "ministry_urls": ["https://example.org/projects/business/x"],
            "official_urls": ["https://example.com/", "not a url"],
        }
    ]
    services = [{"id": "svc_1", "urls": ["https://example.org/services/y"]}]
    urls = subject_urls(projects, services, ["example.com"])
    assert [(item.subject_id, item.key, item.own) for item in urls] == [
        ("prj_1", "example.org/projects/business/x", True),
        ("svc_1", "example.org/services/y", True),
    ]


# --------------------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------------------


def index_of(*items: tuple[str, str, bool]) -> SubjectIndex:
    urls = [SubjectUrl(subject, url, archive_key(url), own) for subject, url, own in items]
    projects = {subject for subject, _, _ in items if subject.startswith("prj_")}
    return SubjectIndex.of(urls, projects)


INDEX = index_of(
    ("prj_alpha", "https://example.org/projects/technologies/example-alpha", True),
    ("prj_alpha", "https://example.com/", False),
    ("prj_business", "https://example.org/projects/business/business", True),
    ("svc_one", "https://example.org/services/example-one", True),
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("example.org/projects/technologies/example-alpha", {"prj_alpha": True}),
        ("example.com", {"prj_alpha": False}),  # an official URL: proposed, not created
        ("example.org/services/example-one", {"svc_one": True}),
        ("example.org/projects/example-alpha", {"prj_alpha": False}),  # pre-relaunch slug
        ("example.org/projects/regions/example-alpha", {"prj_alpha": False}),  # other rubric
        ("example.org/projects/business", {}),  # a rubric listing, not the slug "business"
        ("example.org/projects/page", {}),
        ("example.org/projects/page/example-alpha", {}),  # "page" is no rubric
        ("example.org/projects/regions/example-alpha/more", {}),
        ("example.org/projects/unknown-slug", {}),
        ("example.com/projects/example-alpha", {}),  # another host than the ministry URL's
    ],
)
def test_rows_map_exactly_or_by_slug(key: str, expected: dict[str, bool]) -> None:
    assert INDEX.mappings(key) == expected


def test_the_rubric_slugs_are_the_twelve_of_the_site() -> None:
    assert len(RUBRICS) == 12 and {"technologies", "how-tos", "army"} <= RUBRICS


def test_the_earliest_capture_counts_over_pages_and_urlkeys() -> None:
    first = body_snapshot(
        [HEADER, row("org,example)/a", "20200101000000", "https://example.org/a")]
    )
    second = replace(
        body_snapshot(
            [
                HEADER,
                row("org,example)/a/", "20190101000000", "http://www.example.org/a/"),
                row("org,example)/b", "20190101000000", "http://example.org/b"),
                row("org,example)/b", "20190101000000", "http://example.org/B"),
            ]
        ),
        raw_snapshot_id="raw_second",
    )
    pages = [(parse_cdx_json(first), first), (parse_cdx_json(second), second)]
    found = earliest_by_key(pages)
    assert sorted(found) == ["example.org/a", "example.org/b"]
    assert (found["example.org/a"].timestamp, found["example.org/a"].raw_snapshot_id) == (
        "20190101000000",
        "raw_second",
    )
    assert found["example.org/b"].original == "http://example.org/b"  # ties keep the first


def test_a_capture_names_the_cdx_response_it_was_read_from() -> None:
    cdx = snapshot("synthetic_cdx_exact_limit1")
    (item,) = parse_cdx_json(cdx).rows
    capture = capture_of(item, cdx)
    assert capture.archive_url == "https://web.archive.org/web/20150101000000/http://example.com/"
    assert capture.archive_url == archive_capture_url(item.timestamp, item.original)
    assert capture.request_url == cdx.url
    assert (capture.raw_snapshot_id, capture.fetched_at) == (cdx.raw_snapshot_id, cdx.fetched_at)
    assert capture.cdx_row == item.values


def test_the_collector_declares_events_and_supports_only_limit() -> None:
    assert COLLECTOR.NAME == "wayback"
    assert set(COLLECTOR.DECLARATION) == {"event"}
    assert set(COLLECTOR.PARAMS) == {"limit"}
    assert COLLECTOR.MODES == ()
