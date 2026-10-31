"""C1 ``ministry_projects`` (docs/COLLECTORS.md §8.1): the parsers on the fixtures of
``fixtures/ministry_projects/`` (values asserted against the fixtures' own data), on
synthetic pages for the error paths, and runs against the fixtures with the replay
transport."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from mdt.collectors.base import Candidate, LinkHint, focal_org_id
from mdt.collectors.ministry_projects import (
    PAGE_LINK_SNIPPET,
    is_official_link,
    parse_listing,
    parse_project_page,
    rubric_code,
    with_project_page,
)
from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.tiptap import OutboundLink, tiptap_to_text
from mdt.collectors.parsing.turbostream import find_route, loader_data
from mdt.collectors.thedigital import SiteValues, joined_text
from mdt.config import Settings
from mdt.db.models import FetchLog, Project, RunMessage
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change
from tests.collectors.acceptance import (
    Acceptance,
    acceptance,
    acceptance_settings,
    acceptance_template,
)
from tests.collectors.thedigital_helpers import (
    RAW_ID,
    fixture_snapshot,
    fixture_text,
    synthetic_page,
)

__all__ = ["acceptance", "acceptance_template"]

C1 = "ministry_projects"
VALUES = SiteValues(focal_org_id="org_01EXAMPLEFOCALORGANISATI0", default_licence="cc_by_4_0")
#: The externalUrl of the six link entries, as listed on the two fixture pages.
LINK_ENTRY_URLS = {
    "entry:winwin": "https://winwin.gov.ua",
    "entry:ukrayinskyy-fond-startapiv": "https://usf.com.ua",
    "entry:codeua": "https://codeua.com",
    "entry:united24": "https://u24.gov.ua",
    "entry:united24media": "https://united24media.com",
    "entry:digital-state-ua": "https://digitalstate.gov.ua",
}


def nfc(text: str) -> str:
    """The site writes some letters decomposed; the parsers keep NFC (DATA_MODEL §1.2)."""
    return unicodedata.normalize("NFC", text)


def listing(name: str) -> list[Candidate]:
    return parse_listing(fixture_snapshot(C1, name)).candidates


def raw_entries(name: str) -> list[dict[str, Any]]:
    """The listing entries as decoded from the fixture (independent of the parser)."""
    _, data = find_route(loader_data(fixture_text(C1, name)), ("projects",))
    return list(data["projects"])


def raw_project(name: str) -> dict[str, Any]:
    _, data = find_route(loader_data(fixture_text(C1, name)), ("project",))
    return dict(data["project"])


def project_page(name: str, **kwargs: Any) -> tuple[Candidate, Candidate]:
    result = parse_project_page(fixture_snapshot(C1, name, **kwargs), VALUES)
    partial, document = result.candidates
    return partial, document


# --------------------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------------------


def test_the_two_listing_pages_give_twenty_entries_six_of_them_links() -> None:
    first = parse_listing(fixture_snapshot(C1, "projects_page1"))
    second = parse_listing(fixture_snapshot(C1, "projects_page2"))
    assert (first.total, first.last_page, second.total, second.last_page) == (20, 2, 20, 2)
    entries = first.candidates + second.candidates
    assert (len(first.candidates), len(second.candidates)) == (12, 8)
    assert len({entry.key for entry in entries}) == 20
    links = {entry.key: entry.url for entry in entries if entry.details["type"] == "link"}
    assert links == LINK_ENTRY_URLS
    content = [entry for entry in entries if entry.details["type"] == "content"]
    assert first.next_urls + second.next_urls == [entry.url for entry in content]


def test_a_content_entry_gives_caption_url_and_title_from_the_listing() -> None:
    raw = next(item for item in raw_entries("projects_page1") if item["title"] == "Brave1")
    entry = next(item for item in listing("projects_page1") if item.key == "entry:brave1")
    url = "https://thedigital.gov.ua/projects/technologies/brave1"
    assert (entry.entity_type, entry.url, entry.label, entry.external_id) == (
        "project",
        url,
        "Brave1",
        None,
    )
    assert entry.fields == {
        "name_uk": "Brave1",
        "description_uk": nfc(raw["caption"]),
        "ministry_urls": [url],
    }
    assert entry.details == {"type": "content", "rubric": "technologies"}
    assert entry.evidence.raw_snapshot_id == RAW_ID
    assert entry.evidence.source_url == "https://thedigital.gov.ua/projects"


def test_a_link_entry_gives_its_external_url_and_primary_rubric() -> None:
    entry = next(item for item in listing("projects_page2") if item.key == "entry:united24")
    assert entry.url == "https://u24.gov.ua"
    assert entry.fields["official_urls"] == ["https://u24.gov.ua"]
    assert entry.fields["ministry_categories"] == ["army"]
    assert "ministry_urls" not in entry.fields
    assert entry.details["code_labels"] == {"army": "Армія (rubric army)"}


def test_the_data_body_decodes_to_the_entries_of_page_one() -> None:
    page = parse_listing(fixture_snapshot(C1, "projects_page1"))
    data = parse_listing(fixture_snapshot(C1, "projects_data_turbostream"))
    assert (data.total, data.last_page) == (page.total, page.last_page)
    strip = [replace(entry, evidence=page.candidates[0].evidence) for entry in data.candidates]
    assert strip == page.candidates


@pytest.mark.parametrize(
    ("name", "key", "kind"),
    [
        ("category_how_tos_additional", "entry:diiatsyfrova-hromada", "content"),
        ("category_army", "entry:united24", "link"),
        ("category_regions", "entry:center", "content"),
    ],
)
def test_rubric_listings_are_found_by_their_keys(name: str, key: str, kind: str) -> None:
    result = parse_listing(fixture_snapshot(C1, name))
    assert [(entry.key, entry.details["type"]) for entry in result.candidates] == [(key, kind)]
    assert (result.total, result.last_page) == (1, 1)


# --------------------------------------------------------------------------------------
# Project pages
# --------------------------------------------------------------------------------------


def test_the_brave1_page_gives_its_uuid_text_and_official_url() -> None:
    raw = raw_project("project_brave1_technologies")
    partial, document = project_page("project_brave1_technologies")
    url = "https://thedigital.gov.ua/projects/technologies/brave1"
    assert (partial.key, partial.external_id) == ("entry:brave1", raw["id"])
    assert partial.fields == {"ministry_categories": ["technologies"]}
    assert partial.proposed == {"official_urls": ["https://brave1.gov.ua/"]}
    assert partial.field_snapshots == {"ministry_categories": [RAW_ID], "official_urls": [RAW_ID]}
    assert (document.key, document.external_id, document.url) == (
        f"page:{raw['id']}",
        raw["id"],
        url,
    )
    assert document.fields == {
        "doc_type": "project_page",
        "title": "Brave1",
        "url": url,
        "publisher": "thedigital.gov.ua",
        "publisher_org_id": VALUES.focal_org_id,
        "language": "uk",
        "license": "cc_by_4_0",
    }
    blocks = tiptap_to_text(raw["blocks"])
    assert document.text == joined_text(raw["caption"], blocks.text)
    assert "Платформа Brave1" in (document.text or "").splitlines()
    assert (document.text_snapshot_id, document.extraction_method) == (RAW_ID, "turbo-stream")
    assert document.links == [LinkHint(PAGE_LINK_SNIPPET, subject_key="entry:brave1")]
    assert [link.href for link in blocks.links] == ["https://brave1.gov.ua/"]
    # The official-URL proposal cites the page: the link text as quote, the URL as locator.
    evidence = partial.evidence_of("official_urls")
    assert (evidence.raw_snapshot_id, evidence.locator) == (RAW_ID, "https://brave1.gov.ua/")
    assert evidence.quote == blocks.links[0].text and evidence.quote
    assert partial.evidence_of("ministry_categories") == partial.evidence


def test_additional_rubrics_follow_the_primary_one_with_their_site_labels() -> None:
    partial, document = project_page("project_diiatsyfrova_hromada_additional_rubric")
    assert partial.fields["ministry_categories"] == ["technologies", "how_tos"]
    assert partial.details["code_labels"] == {
        "technologies": "Технології (rubric technologies)",
        "how_tos": "Інструкції (rubric how-tos)",
    }
    assert partial.proposed == {"official_urls": ["https://hromada.gov.ua/"]}
    lines = (document.text or "").splitlines()
    assert any(line.startswith("1353 лідерів та лідерок територіальних громад") for line in lines)


def test_legal_references_and_site_files_are_not_proposed_as_official_urls() -> None:
    raw = raw_project("project_virtual_assets_business")
    partial, document = project_page("project_virtual_assets_business")
    assert partial.proposed == {}
    assert "official_urls" not in partial.field_snapshots
    links = tiptap_to_text(raw["blocks"]).links
    hosts = {link.href.split("/")[2] for link in links}
    assert hosts == {"w1.c1.rada.gov.ua", "cms.thedigital.gov.ua"}
    assert len([link for link in links if "cms.thedigital.gov.ua" in link.href]) == 4
    assert not any(link.href.startswith("mailto:") for link in links)
    assert "Законопроєкт №3637 «Про віртуальні активи»" in (document.text or "")
    europe, europe_page = project_page("project_yevrointegraciya_progress")
    assert europe.proposed == {}  # its links are storage files of the site
    assert "storage.thedigital.gov.ua" in fixture_text(C1, "project_yevrointegraciya_progress")
    assert europe_page.text


def test_two_captures_that_differ_only_in_nonces_give_identical_candidates() -> None:
    page = parse_project_page(fixture_snapshot(C1, "project_yevrointegraciya_progress"), VALUES)
    variant = parse_project_page(fixture_snapshot(C1, "variant_yevrointegraciya_302"), VALUES)
    assert fixture_text(C1, "project_yevrointegraciya_progress") != fixture_text(
        C1, "variant_yevrointegraciya_302"
    )
    assert variant.candidates == page.candidates


def test_the_candidate_url_comes_from_the_data_not_from_the_request() -> None:
    snapshot = fixture_snapshot(C1, "variant_regions_city_same_record")
    assert snapshot.url == "https://thedigital.gov.ua/projects/regions/city"
    partial, document = project_page("variant_regions_city_same_record")
    assert (partial.key, partial.url) == (
        "entry:city",
        "https://thedigital.gov.ua/projects/business/city",
    )
    assert document.fields["url"] == "https://thedigital.gov.ua/projects/business/city"
    assert partial.fields["ministry_categories"] == ["business"]


def test_a_404_is_not_found_without_candidates() -> None:
    result = parse_project_page(fixture_snapshot(C1, "legacy_e_residency_404"), VALUES)
    assert result.not_found and result.candidates == []


def test_without_a_focal_organisation_or_licence_statement_the_fields_stay_out() -> None:
    page = synthetic_page(
        "https://thedigital.gov.ua/projects/business/example",
        "projects.view",
        {
            "project": {
                "id": "00000000-0000-0000-0000-000000000001",
                "title": "Example project",
                "slug": "business/example",
                "rubric": {"name": "Example rubric", "slug": "business"},
                "caption": "Example caption.",
                "blocks": [{"type": "paragraph", "content": [{"type": "text", "text": "Body."}]}],
            }
        },
    )
    result = parse_project_page(page, SiteValues(focal_org_id=None, default_licence=None))
    _, document = result.candidates
    assert "publisher_org_id" not in document.fields and "license" not in document.fields
    assert document.text == "Example caption.\n\nBody."


def test_a_page_with_the_default_licence_when_no_statement_is_found() -> None:
    page = synthetic_page(
        "https://thedigital.gov.ua/projects/business/example",
        "projects.view",
        {"project": {"id": "1", "title": "Example project", "slug": "business/example"}},
    )
    _, document = parse_project_page(page, VALUES).candidates
    assert document.fields["license"] == "cc_by_4_0"
    assert document.text is None and "ministry_categories" not in document.fields


# --------------------------------------------------------------------------------------
# Error paths and helpers
# --------------------------------------------------------------------------------------


def test_pages_without_the_expected_loader_data_raise() -> None:
    plain = synthetic_page("https://thedigital.gov.ua/projects", "other.route", {"example": 1})
    with pytest.raises(ParseError):
        parse_listing(plain)
    with pytest.raises(ParseError):
        parse_project_page(plain, VALUES)
    with pytest.raises(ParseError):
        parse_listing(fixture_snapshot(C1, "legacy_e_residency_404"))
    no_stream = replace(plain, body=b"<html><body><h1>Example</h1></body></html>")
    with pytest.raises(ParseError):
        parse_listing(no_stream)


def _listing_page(*projects: dict[str, Any], last_page: Any = 1) -> Any:
    return synthetic_page(
        "https://thedigital.gov.ua/projects",
        "projects.list",
        {"projects": list(projects), "pagination": {"total": len(projects), "lastPage": last_page}},
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"title": "Example project", "type": "content"},  # no slug
        {"title": "Example project", "type": "other", "slug": "business/example"},
        {"title": "Example project", "type": "link", "slug": "business/example"},  # no URL
        {"type": "content", "slug": "business/example"},  # no title
    ],
)
def test_malformed_entries_fail_the_page(entry: dict[str, Any]) -> None:
    with pytest.raises(ParseError):
        parse_listing(_listing_page(entry))


def test_a_pagination_without_counts_fails_the_page() -> None:
    with pytest.raises(ParseError, match="lastPage"):
        parse_listing(_listing_page(last_page="two"))


def test_rubric_codes_and_official_links() -> None:
    assert rubric_code("how-tos") == "how_tos"
    assert rubric_code("zviazok-ta-internet") == "zviazok_ta_internet"
    official = OutboundLink("https://example.org/", "Example", "linkListItem")
    assert is_official_link(official)
    for href in (
        "https://thedigital.gov.ua/projects",
        "https://cms.thedigital.gov.ua/storage/example.pdf",
        "https://w1.c1.rada.gov.ua/example",
        "https://www.kmu.gov.ua/example",
        "https://example.org/report.PDF",
        "https://example.org/archive.zip",
    ):
        assert not is_official_link(OutboundLink(href, "Example", "linkListItem")), href
    assert not is_official_link(OutboundLink("https://example.org/", "Example", "mark"))
    assert not is_official_link(OutboundLink("https://example.org/", "Example", "buttonsItem"))


def test_the_focal_organisation_comes_from_the_run_settings(tmp_path: Path) -> None:
    settings = acceptance_settings(tmp_path)

    @dataclass
    class Context:
        records: list[dict[str, Any]]
        settings: Settings

        def live_records(self, entity_type: str, fields: Any) -> list[dict[str, Any]]:
            assert (entity_type, list(fields)) == ("organization", ["seed_key"])
            return self.records

    focal = {"id": "org_focal", "seed_key": settings.focal_org_seed_key}
    other = {"id": "org_other", "seed_key": None}
    assert focal_org_id(Context([other, focal], settings)) == "org_focal"  # type: ignore[arg-type]
    assert focal_org_id(Context([other], settings)) is None  # type: ignore[arg-type]


def test_a_page_completes_its_entry_without_replacing_the_listing_values() -> None:
    entry = next(item for item in listing("projects_page1") if item.key == "entry:brave1")
    partial, _ = project_page("project_brave1_technologies", raw_snapshot_id="raw_page")
    merged = with_project_page(entry, partial)
    assert merged.evidence == entry.evidence and merged.url == entry.url
    assert merged.external_id == partial.external_id
    assert merged.fields == {**entry.fields, "ministry_categories": ["technologies"]}
    assert merged.proposed == {"official_urls": ["https://brave1.gov.ua/"]}
    assert merged.snapshots_of("description_uk") == [RAW_ID]
    assert merged.snapshots_of("ministry_categories") == ["raw_page"]
    assert merged.snapshots_of("official_urls") == ["raw_page"]


# --------------------------------------------------------------------------------------
# Runs against the fixtures (replay transport)
# --------------------------------------------------------------------------------------


def _message_details(acceptance: Acceptance, run_id: str, code: str) -> list[dict[str, Any]]:
    with acceptance.db.session() as session, read_transaction(session):
        return [
            dict(details)
            for details in session.scalars(
                select(RunMessage.details).where(
                    RunMessage.run_id == run_id, RunMessage.code == code
                )
            )
        ]


def _project(acceptance: Acceptance, slug: str) -> Project:
    with acceptance.db.session() as session, read_transaction(session):
        row = session.scalars(select(Project).where(Project.slug == slug)).one()
        session.expunge(row)
        return row


def test_a_run_matches_the_seed_projects_and_creates_the_project_pages(
    acceptance: Acceptance,
) -> None:
    run_id = acceptance.run(C1, C1)
    row = acceptance.run_row(run_id)
    assert row["status"] == "partial" and row["complete_listing"]  # 10 pages lack a fixture
    observations = acceptance.observations(C1)
    entries = {key: value for key, value in observations.items() if key.startswith("entry:")}
    assert len(entries) == 20 and all(value["subject_id"] for value in entries.values())
    assert acceptance.proposals(kind="create_entity") == []
    brave1 = _project(acceptance, "brave1")
    assert brave1.ministry_categories == ["technologies"]
    assert brave1.field_meta["description_uk"]["src"] == f"collector:{C1}@{run_id}"
    assert _project(acceptance, "diia").ministry_categories == []  # its page was not read
    assert _project(acceptance, "united24-media").ministry_categories == ["progress"]
    pages = {key: value for key, value in observations.items() if key.startswith("page:")}
    assert len(pages) == 4
    proposals = acceptance.proposals(kind="update_field", field="official_urls")
    official = {row["subject_id"]: row["proposed_value"] for row in proposals}
    assert official == {
        brave1.id: ["https://brave1.gov.ua/"],
        _project(acceptance, "diia-digital-community").id: ["https://hromada.gov.ua/"],
    }
    for row in proposals:  # evidence = the project page, quote = link text, locator = URL
        assert row["locator"] == row["proposed_value"][0] and row["quote"]
        assert row["source_url"].startswith("https://thedigital.gov.ua/projects/")
        assert row["raw_snapshot_id"] == row["payload"]["field_snapshots"]["official_urls"][0]
    unknown = {details["code"] for details in _message_details(acceptance, run_id, "unknown_code")}
    assert unknown == {"how_tos", "army"}
    with acceptance.db.session() as session, read_transaction(session):
        requested = set(session.scalars(select(FetchLog.url).where(FetchLog.run_id == run_id)))
    assert "https://thedigital.gov.ua/projects/technologies/winwin" not in requested
    assert not any(url.startswith("https://winwin.gov.ua") for url in requested)


def test_an_entry_without_a_matching_project_becomes_a_create_entity_proposal(
    acceptance: Acceptance,
) -> None:
    brave1 = _project(acceptance, "brave1")
    with acceptance.db.session() as session:
        apply_change(session, "project", brave1.id, {"ministry_urls": []}, Actor.seed())
    run_id = acceptance.run(C1, C1)
    [proposal] = acceptance.proposals(kind="create_entity")
    assert proposal["payload"]["observation_key"] == "entry:brave1"
    assert proposal["payload"]["site_slug"] == "brave1"
    fields = proposal["payload"]["fields"]
    assert fields["name_uk"] == "Brave1"
    assert fields["ministry_urls"] == ["https://thedigital.gov.ua/projects/technologies/brave1"]
    assert fields["ministry_categories"] == ["technologies"]
    assert proposal["first_run_id"] == run_id
    assert acceptance.observations(C1)["entry:brave1"]["subject_id"] is None


def test_a_run_with_a_limit_reads_only_the_first_entries(acceptance: Acceptance) -> None:
    run_id = acceptance.run(C1, C1, params={"limit": 2})
    row = acceptance.run_row(run_id)
    assert not row["complete_listing"]
    entries = [key for key in acceptance.observations(C1) if key.startswith("entry:")]
    assert len(entries) == 2
