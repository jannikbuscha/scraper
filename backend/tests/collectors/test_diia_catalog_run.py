"""Runs of C3 ``diia_catalog`` through the run framework (docs/COLLECTORS.md §8.3, §12.1):
on a fresh database with the real codebook and seed, against the fixtures of
``backend/tests/fixtures/diia_catalog/`` (the replay transport) or a scripted
``httpx2.MockTransport``; nothing reaches the network. Pages written by the tests
themselves (in a temporary directory) carry obviously synthetic labels."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from mdt.collectors.replay import ReplayTransport
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.throttle import HostThrottle
from mdt.db.models import Project, RawSnapshot, RunMessage, SourceObservation
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.merge import merge
from mdt.domain.revisions import soft_delete
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.collectors.conftest import FIXTURES, FakeClock
from tests.helpers import fields_of, load

__all__ = ["acceptance", "acceptance_template"]

COLLECTOR = "diia_catalog"
DIRECTORY = FIXTURES / COLLECTOR
#: The service pages of the fixture set (slug → fixture).
PAGES = {
    "poshkodzhene-majno": "service_poshkodzhene_majno",
    "reyestraciya-fop": "service_reyestraciya_fop",
    "vityag-pro-nesudimist": "service_vityag_pro_nesudimist",
}
SUBCATEGORY = "https://diia.gov.ua/services/categories/biznesu/pidpriyemnictvo"
EXAMPLE_SUBCATEGORY = "https://diia.gov.ua/services/categories/gromadyanam/example-subcategory"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def run_with(acceptance: Acceptance, transport: httpx2.BaseTransport) -> str:
    """Start and execute one run of C3 on ``transport``."""
    with acceptance.db.session() as session:
        run_id = start_run(
            session, acceptance.settings, RunRequest(COLLECTOR, trigger="cli"), transport=transport
        )
    environment = RunEnvironment(transport=transport, clock=FakeClock(), throttle=HostThrottle())
    execute_run(acceptance.db.factory, acceptance.settings, run_id, environment=environment)
    return run_id


def fixture_copy(target: Path, *, drop: Iterable[str] = ()) -> Path:
    """A copy of the C3 fixture directory without the fixtures named in ``drop``."""
    target.mkdir()
    for meta_path in sorted(DIRECTORY.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text("utf-8"))
        if meta["fixture"] not in drop:
            shutil.copy(meta_path, target)
            shutil.copy(DIRECTORY / meta["body"], target)
    return target


def write_page(directory: Path, name: str, url: str, body: str) -> None:
    """A synthetic page served by the replay transport (written by the test)."""
    (directory / f"{name}.html").write_text(body, "utf-8")
    meta = {
        "fixture": name,
        "body": f"{name}.html",
        "url": url,
        "final_url": url,
        "redirects": [],
        "status": 200,
        "retrieved_at": "2026-10-30T12:00:00.000000Z",
        "headers": {"content-type": "text/html; charset=utf-8"},
    }
    (directory / f"{name}.meta.json").write_text(json.dumps(meta), "utf-8")


def audience_page(*subcategories: str) -> str:
    tiles = "".join(
        f'<div class="services_item"><a class="services_item-title-inner" href="{path}">'
        "Example tile</a></div>"
        for path in subcategories
    )
    return f"<html><body><h1>Example audience</h1>{tiles}</body></html>"


def subcategory_page(audience_path: str, *slugs: str) -> str:
    links = "".join(
        f'<div class="service-acc_item"><a class="service-acc_item-service" '
        f'href="/services/{slug}">Example service</a></div>'
        for slug in slugs
    )
    return (
        '<html><body><ul class="breadcrumb"><li><a href="/">Example home</a></li>'
        f'<li><a href="{audience_path}">Example audience</a></li></ul>'
        f'<h1 class="subcategory-title">Example subcategory</h1>{links}</body></html>'
    )


def h1_of(slug: str) -> str:
    """The ``h1.service-type_title`` of a service fixture, read without the parser."""
    soup = BeautifulSoup((DIRECTORY / f"{PAGES[slug]}.html").read_text("utf-8"), "html.parser")
    heading = soup.select_one("h1.service-type_title")
    assert heading is not None
    return heading.get_text(strip=True)


def bound(acceptance: Acceptance, prefix: str) -> dict[str, str]:
    """Slug → bound record of the observations with key ``<prefix>:<slug>``."""
    return {
        key.split(":", 1)[1]: observation["subject_id"]
        for key, observation in acceptance.observations(COLLECTOR).items()
        if key.startswith(f"{prefix}:") and observation["subject_id"] is not None
    }


def messages(acceptance: Acceptance, run_id: str, code: str) -> list[dict[str, Any]]:
    """The run's messages with ``code``, in order (level, message, url, details)."""
    with acceptance.db.session() as session, read_transaction(session):
        return [
            {"level": row.level, "message": row.message, "url": row.url, "details": row.details}
            for row in session.scalars(
                select(RunMessage)
                .where(RunMessage.run_id == run_id, RunMessage.code == code)
                .order_by(RunMessage.id)
            )
        ]


def snapshot_ids(acceptance: Acceptance, run_id: str, url: str) -> list[str]:
    with acceptance.db.session() as session, read_transaction(session):
        return list(
            session.scalars(
                select(RawSnapshot.id).where(RawSnapshot.run_id == run_id, RawSnapshot.url == url)
            )
        )


def diia_project(acceptance: Acceptance) -> str:
    with acceptance.db.session() as session, read_transaction(session):
        project_id = session.scalar(select(Project.id).where(Project.seed_key == "diia"))
    assert project_id is not None
    return str(project_id)


# --------------------------------------------------------------------------------------
# A run against the fixture set
# --------------------------------------------------------------------------------------


def test_a_run_creates_the_services_under_the_diia_project_and_their_pages(
    acceptance: Acceptance,
) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR)
    row = acceptance.run_row(run_id)
    # The catalogue list and the services sitemap were parsed: the listing is complete.
    # 13 URLs have no fixture (refused), so the run is partial.
    assert (row["status"], row["complete_listing"]) == ("partial", True)
    assert row["stats"]["entities_created"] == 6
    services, documents = bound(acceptance, "service"), bound(acceptance, "page")
    assert sorted(services) == sorted(documents) == sorted(PAGES)
    project_id = diia_project(acceptance)
    with acceptance.db.session() as session:
        for slug in PAGES:
            service = load(session, "service", services[slug])
            url = f"https://diia.gov.ua/services/{slug}"
            assert service["project_id"] == project_id
            assert service["name_uk"] == h1_of(slug)
            assert service["urls"] == [url]
            assert service["verification_status"] == "unverified"
            assert service["kind"] is None and service["status"] is None
            assert service["source_categories"] is None  # the category pages are incomplete
            meta = service["field_meta"]["name_uk"]
            assert meta["src"] == f"collector:{COLLECTOR}@{run_id}"
            assert meta["locked"] is False
            assert meta["raw_snapshot_ids"] == snapshot_ids(acceptance, run_id, url)
            document = fields_of(session, "document", documents[slug])
            assert document["title"] == h1_of(slug)
            assert (document["url"], document["publisher"]) == (url, "diia.gov.ua")
            assert (document["doc_type"], document["language"]) == ("project_page", "uk")
            assert document["license"] == "all_rights_reserved"
            assert (document["source_id"], document["external_id"]) == (COLLECTOR, slug)
            assert document["extraction_method"] == "selector"
            assert document["text_hash"] and document["published"] is None
            [link] = [item for item in document["links"] if item["subject_id"] == services[slug]]
            # The page states its service (a hint); the tagger may suggest it first.
            assert (link["origin"], link["state"]) == ("auto", "suggested")
        channels = fields_of(session, "service", services["poshkodzhene-majno"])["channels"]
    assert channels == ["portal", "physical"]  # "Онлайн", "Офлайн"; "Результат" ignored


def test_listed_services_whose_page_failed_are_sighted(acceptance: Acceptance) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR)
    observations = acceptance.observations(COLLECTOR)
    rd4u = observations["service:RD4U"]  # only in the catalogue list; no fixture
    assert rd4u["subject_id"] is None and rd4u["present"]
    assert rd4u["last_seen_run"] == run_id
    assert rd4u["label"] == "Репарації: міжнародний реєстр збитків"
    assert rd4u["details"] == {"lastmod": None}
    b16 = observations["service:b16-inshi-vtraty-maina"]  # only in the sitemap
    assert b16["details"] == {"lastmod": "2026-09-13T23:15:57+03:00"}
    assert observations["page:RD4U"]["last_seen_run"] == run_id
    fop = observations["service:reyestraciya-fop"]
    assert fop["details"] == {"lastmod": "2019-11-13T10:16:59+02:00"}
    assert fop["external_id"] == "reyestraciya-fop"
    assert len(observations) == 24  # 12 slugs: catalogue list ∪ sitemap, two keys each


def test_incomplete_category_pages_leave_both_fields_out_with_a_warning(
    acceptance: Acceptance,
) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR)
    [warning] = messages(acceptance, run_id, "incomplete_candidate")
    assert warning["level"] == "warning"
    assert warning["details"]["missing"] == [
        "https://diia.gov.ua/services/categories/biznesu",
        "https://diia.gov.ua/services/categories/gromadyanam/yevidnovlennia",
        "https://diia.gov.ua/services/categories/gromadyanam/veteran-pro",
        "https://diia.gov.ua/services/categories/gromadyanam/reparatsii-mizhnarodnyi-reiestr-zbytkiv",
    ]
    with acceptance.db.session() as session:
        for service_id in bound(acceptance, "service").values():
            fields = fields_of(session, "service", service_id)
            assert fields["source_categories"] is None and fields["source_audiences"] == []


def test_category_fields_are_written_when_every_category_page_was_parsed(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    directory = fixture_copy(tmp_path / "complete", drop={"category_gromadyanam"})
    write_page(
        directory,
        "synthetic_audience_gromadyanam",
        "https://diia.gov.ua/services/categories/gromadyanam",
        audience_page("/services/categories/gromadyanam/example-subcategory"),
    )
    write_page(
        directory,
        "synthetic_audience_biznesu",
        "https://diia.gov.ua/services/categories/biznesu",
        audience_page("/services/categories/biznesu/pidpriyemnictvo"),
    )
    write_page(
        directory,
        "synthetic_subcategory",
        EXAMPLE_SUBCATEGORY,
        subcategory_page("/services/categories/gromadyanam", "reyestraciya-fop", "RD4U"),
    )
    run_id = run_with(acceptance, ReplayTransport([directory]))
    assert messages(acceptance, run_id, "incomplete_candidate") == []
    services = bound(acceptance, "service")
    with acceptance.db.session() as session:
        fop = load(session, "service", services["reyestraciya-fop"])
        others = [
            load(session, "service", services[slug])
            for slug in services
            if slug != "reyestraciya-fop"
        ]
    assert fop["source_categories"] == [  # sorted by URL
        {"source": COLLECTOR, "label": "Бізнесу / Підприємництво", "url": SUBCATEGORY},
        {
            "source": COLLECTOR,
            "label": "Example audience / Example subcategory",
            "url": EXAMPLE_SUBCATEGORY,
        },
    ]
    assert fop["source_audiences"] == ["Example audience", "Бізнесу"]
    pages = snapshot_ids(acceptance, run_id, SUBCATEGORY) + snapshot_ids(
        acceptance, run_id, EXAMPLE_SUBCATEGORY
    )
    for name in ("source_categories", "source_audiences"):
        assert fop["field_meta"][name]["raw_snapshot_ids"] == pages
    assert all(other["source_categories"] is None for other in others)

    # The next run without the synthetic subcategory page: the fields are left out of
    # every candidate, so nothing is cleared or rewritten.
    (directory / "synthetic_subcategory.meta.json").unlink()
    before = acceptance.state()
    second = run_with(acceptance, ReplayTransport([directory]))
    assert acceptance.state() == before
    [warning] = messages(acceptance, second, "incomplete_candidate")
    assert warning["details"]["missing"] == [EXAMPLE_SUBCATEGORY]


# --------------------------------------------------------------------------------------
# Completeness and disappearance
# --------------------------------------------------------------------------------------


def test_without_the_services_sitemap_the_listing_is_incomplete(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    first = acceptance.run(COLLECTOR, COLLECTOR)
    directory = fixture_copy(tmp_path / "no-sitemap", drop={"sitemap_index"})
    second = run_with(acceptance, ReplayTransport([directory]))
    assert acceptance.run_row(second)["complete_listing"] is False
    observations = acceptance.observations(COLLECTOR)
    # Only the catalogue list was read; the sitemap's services were not seen, but an
    # incomplete listing never marks a key as missing.
    fop = observations["service:reyestraciya-fop"]
    assert (fop["last_seen_run"], fop["present"]) == (first, True)
    assert observations["service:RD4U"]["last_seen_run"] == second


def test_a_service_that_left_the_listing_becomes_possibly_discontinued(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    acceptance.run(COLLECTOR, COLLECTOR)
    service_id = bound(acceptance, "service")["reyestraciya-fop"]
    directory = fixture_copy(tmp_path / "gone", drop={"sitemap_services"})
    sitemap = (DIRECTORY / "sitemap_services.xml").read_text("utf-8")
    start = sitemap.index("<url>\n\t<loc>https://diia.gov.ua/services/reyestraciya-fop</loc>")
    end = sitemap.index("</url>", start) + len("</url>")
    (directory / "sitemap_services.xml").write_text(sitemap[:start] + sitemap[end:], "utf-8")
    shutil.copy(DIRECTORY / "sitemap_services.meta.json", directory)
    for expected_missing_runs in (1, 2):
        run_id = run_with(acceptance, ReplayTransport([directory]))
        assert acceptance.run_row(run_id)["complete_listing"] is True
        observation = acceptance.observations(COLLECTOR)["service:reyestraciya-fop"]
        assert observation["present"] is False
        assert acceptance.observations(COLLECTOR)["page:reyestraciya-fop"]["present"] is False
        with acceptance.db.session() as session, read_transaction(session):
            missing_runs = session.scalar(
                select(SourceObservation.missing_runs).where(
                    SourceObservation.collector == COLLECTOR,
                    SourceObservation.key == "service:reyestraciya-fop",
                )
            )
        assert missing_runs == expected_missing_runs
    [proposal] = acceptance.proposals(kind="possibly_discontinued")
    assert (proposal["subject_id"], proposal["collector"]) == (service_id, COLLECTOR)
    assert proposal["proposed_value"] == {"status": "discontinued"}


# --------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------


def test_a_deleted_diia_project_fails_the_run_before_any_request(acceptance: Acceptance) -> None:
    with acceptance.db.session() as session:
        soft_delete(session, "project", diia_project(acceptance), Actor.ui(), note="Example")
    run_id = acceptance.run(COLLECTOR, COLLECTOR)
    row = acceptance.run_row(run_id)
    assert row["status"] == "failed"
    assert "seed key 'diia'" in row["error"]
    assert row["stats"]["requests"] == 0
    assert acceptance.state().records["service"] == 0


def test_a_challenge_on_the_listing_host_fails_the_run(acceptance: Acceptance) -> None:
    challenge = "<html><head><title>Just a moment...</title></head><body></body></html>"

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/robots.txt":
            return httpx2.Response(404)
        return httpx2.Response(403, text=challenge, headers={"content-type": "text/html"})

    run_id = run_with(acceptance, httpx2.MockTransport(handler))
    row = acceptance.run_row(run_id)
    assert (row["status"], row["error"]) == ("failed", "diia.gov.ua: blocked")
    assert row["complete_listing"] is False
    assert acceptance.observations(COLLECTOR) == {}


def test_a_page_without_the_expected_structure_is_a_parse_error(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    directory = fixture_copy(tmp_path / "broken", drop={"service_reyestraciya_fop"})
    html = (DIRECTORY / "service_reyestraciya_fop.html").read_text("utf-8")
    write_page(
        directory,
        "synthetic_broken_service",
        "https://diia.gov.ua/services/reyestraciya-fop",
        html.replace("service-type_title", "example-renamed-class"),
    )
    run_id = run_with(acceptance, ReplayTransport([directory]))
    [error] = messages(acceptance, run_id, "parse_error")
    assert error["url"] == "https://diia.gov.ua/services/reyestraciya-fop"
    assert "h1.service-type_title" in error["message"]
    assert "reyestraciya-fop" not in bound(acceptance, "service")
    observation = acceptance.observations(COLLECTOR)["service:reyestraciya-fop"]
    assert observation["last_seen_run"] == run_id  # sighted


def test_a_listed_slug_whose_page_only_redirects_is_sighted_with_a_warning(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    # Synthetic, shaped like the live answer of /services/RD4U on 2026-10-30 (HTTP 200
    # with a meta refresh to a subcategory); RD4U has no fixture of its own.
    directory = fixture_copy(tmp_path / "redirect")
    write_page(
        directory,
        "synthetic_redirect_page",
        "https://diia.gov.ua/services/RD4U",
        '<html><head><meta http-equiv="refresh" content="0;url=\'https://diia.gov.ua/'
        "services/categories/gromadyanam/example-subcategory'\" /></head>"
        "<body>Redirecting to an example page.</body></html>",
    )
    run_id = run_with(acceptance, ReplayTransport([directory]))
    [warning] = messages(acceptance, run_id, "unsupported_content")
    assert warning["url"] == "https://diia.gov.ua/services/RD4U"
    assert "redirects to https://diia.gov.ua/services/categories/gromadyanam/" in warning["message"]
    assert not [
        message
        for message in messages(acceptance, run_id, "parse_error")
        if message["url"] == "https://diia.gov.ua/services/RD4U"
    ]
    observations = acceptance.observations(COLLECTOR)
    assert observations["service:RD4U"]["last_seen_run"] == run_id
    assert observations["page:RD4U"]["last_seen_run"] == run_id
    assert "RD4U" not in bound(acceptance, "service")


def test_limit_caps_the_service_pages_and_never_completes_the_listing(
    acceptance: Acceptance,
) -> None:
    run_id = acceptance.run(COLLECTOR, COLLECTOR, params={"limit": 2})
    row = acceptance.run_row(run_id)
    assert row["complete_listing"] is False
    # Sorted by slug, the first two are "RD4U" (no fixture) and "a210-…" (no fixture).
    assert sorted(acceptance.observations(COLLECTOR)) == [
        "page:RD4U",
        "page:a210-inshi-porushennia-mizhnarodnoho-prava-prav-liudyny-mizhnarodnoho-"
        "humanitarnoho-prava-abo-zakoniv-i-zvychaiv-viiny",
        "service:RD4U",
        "service:a210-inshi-porushennia-mizhnarodnoho-prava-prav-liudyny-mizhnarodnoho-"
        "humanitarnoho-prava-abo-zakoniv-i-zvychaiv-viiny",
    ]


# --------------------------------------------------------------------------------------
# One record, several candidates (docs/COLLECTORS.md §12.1)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("survivor", "merged"),
    [("reyestraciya-fop", "vityag-pro-nesudimist"), ("vityag-pro-nesudimist", "reyestraciya-fop")],
    ids=["survivor-key-first", "merged-key-first"],
)
def test_two_merged_services_are_reconciled_from_the_first_candidate(
    acceptance: Acceptance, survivor: str, merged: str
) -> None:
    acceptance.run(COLLECTOR, COLLECTOR)
    services = bound(acceptance, "service")
    with acceptance.db.session() as session:
        merge(session, "service", services[survivor], services[merged], None, "Example merge")
    first_key, second_key = sorted((survivor, merged))  # C3 reconciles by slug

    second = acceptance.run(COLLECTOR, COLLECTOR)
    with acceptance.db.session() as session:
        kept: dict[str, Any] = fields_of(session, "service", services[survivor])
        retired = load(session, "service", services[merged])
    assert retired["merged_into"] == services[survivor]
    # The survivor holds the values of the first candidate; URL lists only grow.
    assert kept["name_uk"] == h1_of(first_key)
    assert f"https://diia.gov.ua/services/{first_key}" in kept["urls"]
    assert kept["urls"][0] == f"https://diia.gov.ua/services/{survivor}"
    observations = acceptance.observations(COLLECTOR)
    for slug in (survivor, merged):  # both keys were seen; each keeps its own subject
        assert observations[f"service:{slug}"]["last_seen_run"] == second
        assert observations[f"service:{slug}"]["subject_id"] == services[slug]
    conflicts = messages(acceptance, second, "conflicting_candidates")
    assert conflicts
    assert all(
        message["details"]["keys"] == [f"service:{first_key}", f"service:{second_key}"]
        for message in conflicts
    )
    assert {message["details"]["field"] for message in conflicts} >= {"name_uk", "description_uk"}

    before = acceptance.state()
    third = acceptance.run(COLLECTOR, COLLECTOR)
    assert acceptance.state() == before  # a further run writes nothing
    stats = acceptance.run_row(third)["stats"]
    assert (stats["entities_created"], stats["entities_updated"], stats["revisions"]) == (0, 0, 0)
