"""C4 ``ministry_news`` (docs/COLLECTORS.md §8.4): the parsers on the fixtures of
``fixtures/ministry_news/`` (values asserted against the fixtures' own data), derived
variants for the volatility rule, the collector's control flow against synthetic pages (a
fake run context, no database), and runs against the fixtures with the replay transport."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select

from mdt.collectors.base import (
    Candidate,
    Evidence,
    FatalRunError,
    Observation,
    Outcome,
    Snapshot,
)
from mdt.collectors.client import FetchResult
from mdt.collectors.mappings import load_mapping
from mdt.collectors.ministry_news import (
    COLLECTOR,
    MICROSITES,
    listing_only,
    selected_parts,
    up_to_date,
)
from mdt.collectors.ministry_news_pages import (
    document_item,
    parse_article,
    parse_document_page,
    parse_documents_listing,
    parse_microsite,
    parse_ministry_page,
    parse_news_listing,
    storage_md5,
    with_file,
)
from mdt.collectors.parsing import ParseError
from mdt.collectors.parsing.tiptap import tiptap_to_text
from mdt.collectors.parsing.turbostream import find_route, loader_data
from mdt.collectors.sources import load_sources
from mdt.collectors.thedigital import SiteValues, joined_text
from mdt.config import REPO_ROOT, Settings
from mdt.db.models import Document
from mdt.db.session import read_transaction
from tests.api.conftest import api_settings
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.collectors.thedigital_helpers import (
    RAW_ID,
    fixture_snapshot,
    fixture_text,
    synthetic_page,
)

__all__ = ["acceptance", "acceptance_template"]

C4 = "ministry_news"
VALUES = SiteValues(focal_org_id="org_01EXAMPLEFOCALORGANISATI0", default_licence="cc_by_4_0")
KINDS = load_mapping(REPO_ROOT / "codebook", "ministry_document_kinds")
PDF_MD5 = "fa231dbe2422c63e946dc25c3c26f154"
SITE = "https://thedigital.gov.ua"


def nfc(text: str) -> str:
    """The site writes some letters decomposed; the parsers keep NFC (DATA_MODEL §1.2)."""
    return unicodedata.normalize("NFC", text)


def raw_entry(name: str, *keys: str) -> dict[str, Any]:
    """The loader entry of a fixture with one of ``keys`` (decoded independently)."""
    _, data = find_route(loader_data(fixture_text(C4, name)), keys)
    return dict(data)


def article(name: str, **kwargs: Any) -> Candidate:
    [candidate] = parse_article(fixture_snapshot(C4, name, **kwargs), VALUES).candidates
    return candidate


# --------------------------------------------------------------------------------------
# News
# --------------------------------------------------------------------------------------


def test_the_first_and_last_news_pages_give_their_items_and_pagination() -> None:
    first = parse_news_listing(fixture_snapshot(C4, "news_list_page1"))
    last = parse_news_listing(fixture_snapshot(C4, "news_list_page366"))
    assert (first.total, first.last_page, len(first.candidates)) == (4385, 366, 12)
    assert (last.total, last.last_page, len(last.candidates)) == (4385, 366, 5)
    raw = raw_entry("news_list_page1", "articles")["articles"][0]
    item = first.candidates[0]
    url = f"https://thedigital.gov.ua/news/{raw['slug']}"
    assert (item.key, item.url, item.label) == (
        f"news:{raw['slug'].rsplit('/', 1)[-1]}",
        url,
        nfc(raw["title"]),
    )
    assert item.fields == {} and item.external_id is None
    assert item.details == {
        "title": nfc(raw["title"]),
        "published_at": raw["publishedAt"]["iso8601"],
        "url": url,
    }
    assert "related" in raw["publishedAt"]  # never read
    oldest = raw_entry("news_list_page366", "articles")["articles"][-1]
    assert "related" not in oldest["publishedAt"]
    assert last.candidates[-1].details["published_at"] == "2019-10-07T11:48:00+03:00"


@pytest.mark.parametrize(
    ("name", "published", "utc"),
    [
        ("news_article_2019", "2019-10-11", "2019-10-11T10:21:00.000000Z"),
        ("news_article_2022", "2022-05-20", "2022-05-20T09:54:41.000000Z"),
        ("news_article_2026", "2026-10-01", "2026-10-01T13:00:00.000000Z"),
    ],
)
def test_articles_are_dated_by_the_kyiv_date_of_their_iso_timestamp(
    name: str, published: str, utc: str
) -> None:
    raw = raw_entry(name, "article")["article"]
    candidate = article(name)
    url = f"https://thedigital.gov.ua/news/{raw['slug']}"
    assert (candidate.key, candidate.external_id, candidate.url) == (
        f"news:{raw['slug'].rsplit('/', 1)[-1]}",
        raw["id"],
        url,
    )
    assert candidate.fields == {
        "doc_type": "news",
        "title": nfc(raw["title"]),
        "url": url,
        "publisher": "thedigital.gov.ua",
        "publisher_org_id": VALUES.focal_org_id,
        "language": "uk",
        "license": "cc_by_4_0",
        "published": published,
        "published_basis": "stated_in_source",
        "published_text": raw["publishedAt"]["iso8601"],
        "published_at_utc": utc,
    }
    lead = tiptap_to_text(raw.get("lead")).text
    assert candidate.text == joined_text(lead, tiptap_to_text(raw["blocks"]).text)
    assert (candidate.text_snapshot_id, candidate.extraction_method) == (RAW_ID, "turbo-stream")


def test_the_lead_comes_before_the_blocks() -> None:
    raw = raw_entry("news_article_2026", "article")["article"]
    lead = tiptap_to_text(raw["lead"]).text
    candidate = article("news_article_2026")
    assert lead and (candidate.text or "").startswith(lead)


def test_an_english_article_in_the_ukrainian_feed_is_english() -> None:
    raw = raw_entry("news_article_en_2024", "article")["article"]
    assert [item["language"]["code"] for item in raw["translations"]] == ["uk"]
    assert article("news_article_en_2024").fields["language"] == "en"


def test_a_redirected_article_takes_its_url_from_the_data() -> None:
    snapshot = fixture_snapshot(C4, "news_article_redirect_2021")
    assert snapshot.redirects and snapshot.url != snapshot.final_url
    candidate = article("news_article_redirect_2021")
    assert candidate.url == snapshot.final_url == candidate.fields["url"]
    assert candidate.evidence.source_url == snapshot.final_url


def test_a_404_page_is_not_found() -> None:
    for parser in (
        lambda snapshot: parse_article(snapshot, VALUES),
        lambda snapshot: parse_document_page(snapshot, KINDS, VALUES),
        lambda snapshot: parse_ministry_page(snapshot, KINDS, VALUES),
        parse_microsite,
    ):
        result = parser(fixture_snapshot(C4, "not_found_en"))
        assert result.not_found and result.candidates == []


def test_an_article_without_an_iso_date_has_no_date_and_a_warning() -> None:
    page = synthetic_page(
        "https://thedigital.gov.ua/news/business/example",
        "news.view",
        {
            "article": {
                "id": "1",
                "title": "Example article",
                "slug": "business/example",
                "publishedAt": {"date": "2020-01-01", "text": "01 січ. 2020"},
            }
        },
    )
    result = parse_article(page, VALUES)
    [candidate] = result.candidates
    assert "published" not in candidate.fields and "published_text" not in candidate.fields
    assert [code for code, _ in result.warnings] == ["invalid_value"]


# --------------------------------------------------------------------------------------
# Volatility (DATA_MODEL §15.6): derived variants of the news fixtures
# --------------------------------------------------------------------------------------


def _variant(text: str) -> bytes:
    """Change the volatile parts: CSP nonces, relative times and image ``?v=`` values."""
    for nonce in set(_between(text, 'nonce="', '"')):
        text = text.replace(nonce, "ExampleNonce" + nonce[::-1][:8])
    for related in ("1 день тому", "1 тиждень тому", "4 тижні тому"):
        text = text.replace(related, "щойно")
    for version in set(_between(text, "?v=", '"')):
        text = text.replace(f"?v={version}", f"?v=9{version}")
    return text.encode("utf-8")


def _between(text: str, start: str, end: str) -> list[str]:
    found = []
    position = text.find(start)
    while position != -1:
        stop = text.find(end, position + len(start))
        found.append(text[position + len(start) : stop])
        position = text.find(start, stop)
    return found


@pytest.mark.parametrize("name", ["news_list_page1", "news_article_2026"])
def test_volatile_parts_never_reach_a_candidate(name: str) -> None:
    original = fixture_text(C4, name)
    variant = _variant(original)
    assert variant != original.encode("utf-8")
    if name.startswith("news_list"):
        first = parse_news_listing(fixture_snapshot(C4, name))
        second = parse_news_listing(fixture_snapshot(C4, name, body=variant))
    else:
        first = parse_article(fixture_snapshot(C4, name), VALUES)
        second = parse_article(fixture_snapshot(C4, name, body=variant), VALUES)
    assert second.candidates == first.candidates


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


def test_file_items_are_keyed_by_the_md5_file_name_and_typed_by_kind() -> None:
    result = parse_documents_listing(fixture_snapshot(C4, "documents_list_page1"), KINDS)
    assert (result.total, result.last_page, len(result.candidates)) == (1267, 106, 12)
    assert result.warnings == []
    raw = raw_entry("documents_list_page1", "documents")["documents"]
    for item, entry in zip(result.candidates, raw, strict=True):
        assert item.details["type"] == entry["type"]
        assert item.details["kind"] == entry["kind"]["slug"]
        assert item.fields["doc_type"] == KINDS.lookup(entry["kind"]["slug"]).code
        assert "published" not in item.fields
    files = [item for item in result.candidates if item.details["type"] == "file"]
    first = files[0]
    md5 = raw[0]["externalUrl"].rsplit("/", 1)[-1].split(".")[0]
    assert first.key == f"file:{md5}" and first.url == raw[0]["externalUrl"]
    assert first.fields == {
        "title": nfc(raw[0]["title"]),
        "doc_type": "legal_act",  # kind "resolution"
        "source_record_at": "2026-10-28T12:49:21.000000Z",
        "license": "unknown",
        "url": raw[0]["externalUrl"],
    }
    assert first.text is None and first.extraction_method is None
    content = [item for item in result.candidates if item.details["type"] == "content"]
    assert content and all(
        item.url == f"https://thedigital.gov.ua/documents/{item.key.removeprefix('doc:')}"
        for item in content
    )


def test_link_items_carry_the_act_date_only_as_the_site_record_date() -> None:
    snapshot = fixture_snapshot(C4, "documents_list_page106")
    result = parse_documents_listing(snapshot, KINDS)
    assert len(result.candidates) == 7
    assert all(item.details["type"] == "link" for item in result.candidates)
    raw = raw_entry("documents_list_page106", "documents")["documents"]
    last = result.candidates[-1]
    assert last.key == f"doc:{raw[-1]['slug']}"
    assert last.url == raw[-1]["externalUrl"]
    assert last.fields["source_record_at"] == "1996-03-10T22:00:00.000000Z"
    assert raw[-1]["publishedAt"]["iso8601"] == "1996-03-11T00:00:00+02:00"
    for item in result.candidates:
        assert "published" not in item.fields and "published_text" not in item.fields
        assert (item.text, item.extraction_method) == (None, "listing_only")
        assert item.text_snapshot_id == RAW_ID
        assert item.fields["source_record_at"][:4] in {"1996", "1999", "2000", "2001"}


def test_a_content_page_gives_its_text_and_one_file_document_per_attachment() -> None:
    raw = raw_entry("document_page_content", "document")["document"]
    result = parse_document_page(fixture_snapshot(C4, "document_page_content"), KINDS, VALUES)
    document, *attachments = result.candidates
    url = f"https://thedigital.gov.ua/documents/{raw['slug']}"
    assert (document.key, document.external_id, document.url) == (
        f"doc:{raw['slug']}",
        raw["id"],
        url,
    )
    assert document.fields == {
        "title": nfc(raw["title"]),
        "url": url,
        "doc_type": "other",  # kind "project"
        "publisher": "thedigital.gov.ua",
        "language": "uk",
        "source_record_at": "2026-09-03T14:48:12.000000Z",
        "license": "cc_by_4_0",
    }
    assert document.text == tiptap_to_text(raw["blocks"]).text
    links = list(tiptap_to_text(raw["blocks"]).links)
    assert [item.key for item in attachments] == [
        f"file:{storage_md5(link.href)}" for link in links
    ]
    assert attachments[0].key == f"file:{PDF_MD5}"
    for item, link in zip(attachments, links, strict=True):
        assert item.fields == {
            "title": link.text,
            "url": link.href,
            "license": "unknown",
            "doc_type": "other",
        }
        assert item.details == {
            "type": "file",
            "kind": "project",
            "title": link.text,
            "url": link.href,
        }


def test_the_stored_pdf_gives_its_text_and_matches_its_md5_name() -> None:
    result = parse_document_page(fixture_snapshot(C4, "document_page_content"), KINDS, VALUES)
    item = result.candidates[1]
    pdf = fixture_snapshot(C4, "storage_pdf_draft_resolution", raw_snapshot_id="raw_pdf")
    assert hashlib.md5(pdf.body, usedforsecurity=False).hexdigest() == PDF_MD5
    candidate, warnings = with_file(item, pdf)
    assert warnings == []
    assert (candidate.extraction_method, candidate.text_snapshot_id) == ("pdf", "raw_pdf")
    assert candidate.text and "КАБІНЕТ МІНІСТРІВ УКРАЇНИ" in candidate.text
    assert candidate.fields["language"] == "uk"
    assert candidate.snapshots_of("language") == ["raw_pdf"]
    assert candidate.snapshots_of("title") == [RAW_ID]
    assert candidate.details["fetched"] is True
    changed = replace(pdf, body=pdf.body + b"\n")
    _, warnings = with_file(item, changed)
    assert [code for code, _ in warnings] == ["checksum_mismatch"]


def test_a_file_of_another_type_is_kept_without_text() -> None:
    item = Candidate(
        entity_type="document",
        key="file:" + "0" * 32,
        evidence=Evidence(raw_snapshot_id=RAW_ID, source_url=f"{SITE}/documents"),
        url="https://storage.thedigital.gov.ua/files/0/00/" + "0" * 32 + ".xlsx",
        fields={"title": "Example table"},
        details={"type": "file"},
    )
    body = b"PK\x03\x04example"
    snapshot = replace(
        fixture_snapshot(C4, "storage_pdf_draft_resolution"),
        body=body,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    candidate, warnings = with_file(item, snapshot)
    assert (candidate.text, candidate.extraction_method) == (None, "none")
    assert "language" not in candidate.fields
    assert [code for code, _ in warnings] == ["checksum_mismatch"]


def test_the_ministry_page_gives_its_text_and_its_embedded_documents() -> None:
    raw = raw_entry("ministry_page", "page")["page"]
    result = parse_ministry_page(fixture_snapshot(C4, "ministry_page"), KINDS, VALUES)
    page, *items = result.candidates
    assert (page.key, page.external_id, page.url) == (
        "page:ministry",
        raw["id"],
        "https://thedigital.gov.ua/ministry",
    )
    assert page.fields == {
        "doc_type": "other",
        "title": nfc(raw["title"]),
        "url": "https://thedigital.gov.ua/ministry",
        "publisher": "thedigital.gov.ua",
        "language": "uk",
        "license": "cc_by_4_0",
    }
    nodes = _nodes(raw["blocks"])
    tabs = [node["attrs"]["label"] for node in nodes if node.get("type") == "tabsItem"]
    lines = (page.text or "").splitlines()
    assert len(tabs) == 5 and all(nfc(label).strip() in lines for label in tabs)
    members = [
        member["fullName"]
        for node in nodes
        if node.get("type") == "teamMembers"
        for member in node["attrs"]["teamMembers"]
    ]
    assert members and not any(name in (page.text or "") for name in members)
    related = [
        item
        for node in nodes
        if node.get("type") == "relatedDocuments"
        for item in node["attrs"]["documents"]
    ]
    assert len(items) == len(related) == 33
    plans = [item for item in items if item.details["kind"] == "regulation"]
    assert plans and all(item.fields["doc_type"] == "other" for item in plans)
    first, _ = document_item(related[0], fixture_snapshot(C4, "ministry_page"), KINDS)
    assert items[0] == first


def _nodes(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [found for child in node for found in _nodes(child)]
    if not isinstance(node, dict):
        return []
    return [node, *_nodes(node.get("content"))]


@pytest.mark.parametrize(
    ("name", "licence"),
    [("microsite_2years_report", "cc_by_4_0"), ("microsite_2025_report", "unknown")],
)
def test_microsites_take_their_licence_from_their_own_statement(name: str, licence: str) -> None:
    snapshot = fixture_snapshot(C4, name)
    [candidate] = parse_microsite(snapshot).candidates
    host = snapshot.url.split("/")[2] if snapshot.url else ""
    assert (candidate.key, candidate.url) == (f"microsite:{host}", snapshot.url)
    assert candidate.fields["doc_type"] == "report"
    assert candidate.fields["license"] == licence
    assert candidate.fields["publisher"] == host
    assert "published" not in candidate.fields
    assert candidate.extraction_method == "html" and candidate.text


def test_an_unmapped_kind_gets_the_fallback_and_a_warning() -> None:
    entry = {
        "type": "link",
        "slug": "legislation/example",
        "title": "Example act",
        "kind": {"slug": "example-kind"},
        "externalUrl": "https://example.org/act",
        "publishedAt": {"iso8601": "2020-01-01T00:00:00+02:00"},
    }
    snapshot = fixture_snapshot(C4, "documents_list_page106")
    item, warnings = document_item(entry, snapshot, KINDS)
    assert item.fields["doc_type"] == "other"
    assert [code for code, _ in warnings] == ["unmapped_label"]
    with pytest.raises(ParseError):
        document_item({**entry, "type": "example"}, snapshot, KINDS)
    with pytest.raises(ParseError):
        document_item({**entry, "type": "file", "externalUrl": None}, snapshot, KINDS)
    other_file, _ = document_item({**entry, "type": "file"}, snapshot, KINDS)
    assert other_file.key == "doc:legislation/example"  # not a storage file name


def test_storage_md5_and_the_parts_option() -> None:
    assert storage_md5(f"https://storage.thedigital.gov.ua/files/5/15/{PDF_MD5}.pdf") == PDF_MD5
    assert storage_md5(f"https://example.org/files/5/15/{PDF_MD5}.pdf") is None
    assert storage_md5("https://storage.thedigital.gov.ua/files/example.pdf") is None
    assert selected_parts({}) == frozenset({"news", "documents", "ministry", "microsites"})
    assert selected_parts({"parts": ["news"]}) == frozenset({"news"})
    for value in (["news", "example"], [], "news"):
        with pytest.raises(FatalRunError):
            selected_parts({"parts": value})


# --------------------------------------------------------------------------------------
# The collector's control flow against synthetic pages (no database, no network)
# --------------------------------------------------------------------------------------


def _observation(key: str, details: Mapping[str, Any]) -> Observation:
    return Observation(
        id=1,
        collector=C4,
        key=key,
        entity_type="document",
        subject_id=None,
        bound_by=None,
        bound_at=None,
        external_id=None,
        url=None,
        label=None,
        first_seen_at="2026-01-01T00:00:00.000000Z",
        first_seen_run="run_example",
        last_seen_at="2026-01-01T00:00:00.000000Z",
        last_seen_run="run_example",
        present=True,
        missing_since_at=None,
        missing_since_run=None,
        missing_runs=0,
        last_snapshot_id=None,
        details=dict(details),
    )


@dataclass
class FakeClient:
    """Answers GETs from synthetic snapshots; an int is an HTTP error, a missing URL is
    refused."""

    pages: dict[str, Snapshot | int]
    config: Any
    requested: list[str] = field(default_factory=list)
    listing_host: str | None = None

    def get(self, url: str, **_options: Any) -> FetchResult:
        self.requested.append(url)
        page = self.pages.get(url)
        if isinstance(page, Snapshot):
            return FetchResult(url=url, outcome="ok", status=page.http_status, snapshot=page)
        if page is None:
            return FetchResult(url=url, outcome="refused")
        return FetchResult(url=url, outcome="http_error", status=page)

    def set_listing_host(self, host: str | None) -> None:
        self.listing_host = host

    def listing_done(self) -> None:
        return None


@dataclass
class FakeRun:
    """A run context that records what the collector does; observations are kept like
    the domain layer keeps them (details merged)."""

    client: FakeClient
    settings: Settings
    mode: str = "incremental"
    params: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    run_id: str = "run_example"
    stored: dict[str, Observation] = field(default_factory=dict)
    reconciled: list[Candidate] = field(default_factory=list)
    sightings: list[str] = field(default_factory=list)
    messages: list[tuple[str, str]] = field(default_factory=list)
    complete: bool = False

    def _see(self, key: str, details: Mapping[str, Any] | None) -> None:
        before = self.stored.get(key)
        merged = {**(before.details if before else {}), **(details or {})}
        self.stored[key] = _observation(key, merged)

    def reconcile(self, candidate: Candidate) -> Outcome:
        self.reconciled.append(candidate)
        self._see(candidate.key, candidate.details)
        return Outcome("created")

    def observe(self, entity_type: str, key: str, **context: Any) -> None:
        self.sightings.append(key)
        self._see(key, context.get("details"))

    def observation(self, key: str) -> Observation | None:
        return self.stored.get(key)

    def message(self, level: str, code: str, text: str, **_context: Any) -> None:
        self.messages.append((level, code))

    def count(self, key: str, n: int = 1) -> None:
        return None

    def cancelled(self) -> bool:
        return False

    def listing_complete(self) -> None:
        self.complete = True

    def live_records(self, entity_type: str, fields: Any) -> list[dict[str, Any]]:
        if entity_type == "organization":
            return [{"id": "org_example", "seed_key": self.settings.focal_org_seed_key}]
        codebook = yaml.safe_load((REPO_ROOT / "codebook" / "doc_type.yaml").read_text("utf-8"))
        return [
            {"id": f"voc_{term['code']}", "vocabulary": "doc_type", "code": term["code"]}
            | {"active": term["active"]}
            for term in codebook["terms"]
        ]

    def run(self) -> None:
        COLLECTOR.run(self)  # type: ignore[arg-type]

    def keys(self) -> list[str]:
        return [candidate.key for candidate in self.reconciled]


def news_page(number: int, slugs: list[str], last_page: int, *, title: str = "Example") -> Snapshot:
    url = f"{SITE}/news" if number == 1 else f"{SITE}/news/page/{number}"
    articles = [
        {
            "title": f"{title} {slug}",
            "slug": f"technologies/{slug}",
            "publishedAt": {"iso8601": "2020-01-01T10:00:00+02:00", "related": "1 день тому"},
        }
        for slug in slugs
    ]
    data = {"articles": articles, "pagination": {"total": 3 * last_page, "lastPage": last_page}}
    return synthetic_page(url, "news.list", data, raw_snapshot_id=f"raw_news_{number}")


def article_page(slug: str) -> Snapshot:
    return synthetic_page(
        f"{SITE}/news/technologies/{slug}",
        "news.view",
        {
            "article": {
                "id": f"id-{slug}",
                "title": f"Example article {slug}",
                "slug": f"technologies/{slug}",
                "blocks": [{"type": "paragraph", "content": [{"type": "text", "text": "Text."}]}],
                "publishedAt": {"iso8601": "2020-01-01T10:00:00+02:00"},
            }
        },
        raw_snapshot_id=f"raw_article_{slug}",
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return api_settings(tmp_path)


def fake_run(settings: Settings, pages: dict[str, Snapshot | int], **kwargs: Any) -> FakeRun:
    config = load_sources(settings.sources_path).get(C4)
    return FakeRun(FakeClient(pages, config), settings, **kwargs)


def test_a_failed_article_is_sighted_and_fetched_again_next_run(settings: Settings) -> None:
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, ["a1", "a2"], 2),
        f"{SITE}/news/page/2": news_page(2, ["b1"], 2),
        **{f"{SITE}/news/technologies/{slug}": article_page(slug) for slug in ("a1", "b1")},
    }
    run = fake_run(settings, pages, options={"parts": ["news"]})
    run.run()
    assert run.client.listing_host == "thedigital.gov.ua"
    assert run.keys() == ["news:a1", "news:b1"]
    assert run.reconciled[0].details["title"] == "Example a1"  # the listing values
    assert run.sightings == ["news:a2"]  # its page is missing: sighted without details
    assert not run.complete
    second = fake_run(settings, pages, options={"parts": ["news"]}, stored=dict(run.stored))
    second.run()
    assert second.keys() == [] and f"{SITE}/news/technologies/a2" in second.client.requested
    assert second.sightings == ["news:a1", "news:a2", "news:b1"]


def test_a_failed_listing_page_ends_an_incremental_run_but_not_a_full_one(
    settings: Settings,
) -> None:
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, ["a1"], 3),
        f"{SITE}/news/technologies/a1": article_page("a1"),
    }
    incremental = fake_run(settings, pages, options={"parts": ["news"]})
    incremental.run()
    assert f"{SITE}/news/page/3" not in incremental.client.requested
    full = fake_run(settings, pages, options={"parts": ["news"]}, mode="full")
    full.run()
    assert full.client.requested[-2:] == [f"{SITE}/news/page/2", f"{SITE}/news/page/3"]


def test_incremental_news_stops_after_two_known_pages(settings: Settings) -> None:
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, ["a1"], 5),
        f"{SITE}/news/page/2": news_page(2, ["b1"], 5),
        f"{SITE}/news/page/3": news_page(3, ["c1"], 5),
        **{f"{SITE}/news/technologies/{slug}": article_page(slug) for slug in ("a1", "b1", "c1")},
    }
    first = fake_run(settings, pages, options={"parts": ["news"]}, mode="full")
    first.run()
    second = fake_run(settings, pages, options={"parts": ["news"]}, stored=dict(first.stored))
    second.run()
    assert second.client.requested == [f"{SITE}/news", f"{SITE}/news/page/2"]
    assert second.sightings == ["news:a1", "news:b1"]
    third = fake_run(
        settings, pages, options={"parts": ["news"]}, params={"refetch": True}, stored=first.stored
    )
    third.run()
    assert third.keys() == ["news:a1", "news:b1"]  # refetch reads known articles again


def test_a_listing_that_changes_during_the_run_is_followed_with_a_warning(
    settings: Settings,
) -> None:
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, ["a1"], 2),
        f"{SITE}/news/page/2": news_page(2, ["b1"], 3),
        f"{SITE}/news/page/3": news_page(3, ["c1"], 3),
        **{f"{SITE}/news/technologies/{slug}": article_page(slug) for slug in ("a1", "b1", "c1")},
    }
    run = fake_run(settings, pages, options={"parts": ["news"]}, mode="full")
    run.run()
    assert run.keys() == ["news:a1", "news:b1", "news:c1"]
    assert run.messages == [("warning", "listing_changed")]


def test_a_changed_listing_title_fetches_the_article_again(settings: Settings) -> None:
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, ["a1"], 1),
        f"{SITE}/news/technologies/a1": article_page("a1"),
    }
    first = fake_run(settings, pages, options={"parts": ["news"]}, mode="full")
    first.run()
    pages[f"{SITE}/news"] = news_page(1, ["a1"], 1, title="Changed")
    second = fake_run(
        settings, pages, options={"parts": ["news"]}, mode="full", stored=first.stored
    )
    second.run()
    assert second.keys() == ["news:a1"]
    assert second.reconciled[0].details["title"] == "Changed a1"


def documents_page(number: int, items: list[dict[str, Any]], last_page: int) -> Snapshot:
    url = f"{SITE}/documents" if number == 1 else f"{SITE}/documents/page/{number}"
    data = {"documents": items, "pagination": {"total": len(items), "lastPage": last_page}}
    return synthetic_page(url, "documents.list", data, raw_snapshot_id=f"raw_documents_{number}")


def storage_file(body: bytes, extension: str = "txt") -> tuple[str, Snapshot]:
    md5 = hashlib.md5(body, usedforsecurity=False).hexdigest()
    url = f"https://storage.thedigital.gov.ua/files/{md5[-1]}/{md5[-3:-1]}/{md5}.{extension}"
    page = synthetic_page(url, "unused", {}, raw_snapshot_id=f"raw_file_{md5[:6]}")
    return url, replace(page, body=body, content_type="text/plain", headers={})


def _file_item(url: str, title: str = "Example file") -> dict[str, Any]:
    return {
        "type": "file",
        "slug": "community/example-file",
        "title": title,
        "kind": {"slug": "report"},
        "externalUrl": url,
        "publishedAt": {"iso8601": "2025-01-01T10:00:00+02:00"},
    }


def test_a_file_is_fetched_once_and_later_only_compared(settings: Settings) -> None:
    url, file = storage_file(b"Example file text.")
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/documents": documents_page(1, [_file_item(url)], 1),
        url: file,
    }
    first = fake_run(settings, pages, options={"parts": ["documents"]}, mode="full")
    first.run()
    [candidate] = first.reconciled
    assert candidate.text == "Example file text." and candidate.extraction_method == "txt"
    assert candidate.fields["doc_type"] == "report"
    second = fake_run(
        settings, pages, options={"parts": ["documents"]}, mode="full", stored=first.stored
    )
    second.run()
    assert second.reconciled == [] and url not in second.client.requested
    assert second.sightings == [candidate.key]
    pages[f"{SITE}/documents"] = documents_page(1, [_file_item(url, "Example renamed")], 1)
    third = fake_run(
        settings, pages, options={"parts": ["documents"]}, mode="full", stored=first.stored
    )
    third.run()
    assert url not in third.client.requested  # a known file key is never fetched again
    [renamed] = third.reconciled
    assert renamed.fields["title"] == "Example renamed" and renamed.text is None


def test_a_failed_file_is_kept_from_the_listing_and_fetched_again(settings: Settings) -> None:
    url, file = storage_file(b"Example file text.")
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/documents": documents_page(1, [_file_item(url)], 1)
    }
    first = fake_run(settings, pages, options={"parts": ["documents"]}, mode="full")
    first.run()
    [kept] = first.reconciled
    assert kept.text is None and kept.fields["title"] == "Example file"
    assert kept.details == {"type": "file"}
    pages[url] = file
    second = fake_run(
        settings, pages, options={"parts": ["documents"]}, mode="full", stored=first.stored
    )
    second.run()
    [read] = second.reconciled
    assert read.text == "Example file text." and url in second.client.requested


def test_content_items_read_their_page_and_attachments_once(settings: Settings) -> None:
    url, file = storage_file(b"Example attachment text.")
    content = {
        "type": "content",
        "slug": "ministry/example",
        "title": "Example notice",
        "kind": {"slug": "project"},
        "publishedAt": {"iso8601": "2025-01-01T10:00:00+02:00"},
    }
    page = synthetic_page(
        f"{SITE}/documents/ministry/example",
        "documents.view",
        {
            "document": {
                "id": "id-example",
                "slug": "ministry/example",
                "title": "Example notice",
                "kind": {"slug": "project"},
                "publishedAt": {"iso8601": "2025-01-01T10:00:00+02:00"},
                "blocks": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Example draft",
                                "marks": [{"type": "link", "attrs": {"href": url}}],
                            }
                        ],
                    }
                ],
            }
        },
    )
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/documents": documents_page(1, [content, _file_item(url)], 1),
        f"{SITE}/documents/ministry/example": page,
        url: file,
    }
    first = fake_run(settings, pages, options={"parts": ["documents"]}, mode="full")
    first.run()
    md5_key = f"file:{storage_md5(url)}"
    assert first.keys() == [md5_key, "doc:ministry/example"]  # the listed file comes later
    assert first.reconciled[0].fields["title"] == "Example draft"  # the link text wins
    assert first.stored["doc:ministry/example"].details["attachments"] == [md5_key]
    assert first.client.requested.count(url) == 1
    second = fake_run(
        settings, pages, options={"parts": ["documents"]}, mode="full", stored=first.stored
    )
    second.run()
    assert second.reconciled == []
    assert second.sightings == ["doc:ministry/example", md5_key]
    assert first.complete is False  # documents alone never complete the listing


def test_a_full_run_of_every_part_completes_the_listing(settings: Settings) -> None:
    url, file = storage_file(b"Example file text.")
    ministry = synthetic_page(
        f"{SITE}/ministry",
        "pages.view",
        {
            "page": {
                "id": "id-ministry",
                "title": "Example page",
                "slug": "ministry",
                "blocks": [{"type": "relatedDocuments", "attrs": {"documents": [_file_item(url)]}}],
            }
        },
    )
    pages: dict[str, Snapshot | int] = {
        f"{SITE}/news": news_page(1, [], 1),
        f"{SITE}/documents": documents_page(1, [_file_item(url)], 1),
        url: file,
        f"{SITE}/ministry": ministry,
        **dict.fromkeys(MICROSITES, 404),
    }
    run = fake_run(settings, pages, mode="full")
    run.run()
    assert run.complete
    assert run.keys() == [f"file:{storage_md5(url)}", "page:ministry"]  # the file once
    incremental = fake_run(settings, pages)
    incremental.run()
    assert not incremental.complete
    limited = fake_run(settings, pages, mode="full", params={"limit": 1})
    limited.run()
    assert len(limited.reconciled) == 1 and not limited.complete


def test_listing_only_drops_the_compared_details() -> None:
    snapshot = fixture_snapshot(C4, "documents_list_page1")
    item, _ = document_item(
        raw_entry("documents_list_page1", "documents")["documents"][0], snapshot, KINDS
    )
    assert listing_only(item).details == {"type": "file"}
    assert listing_only(item).fields == item.fields
    assert up_to_date(_observation(item.key, item.details), item)
    assert not up_to_date(_observation(item.key, {"type": "file"}), item)
    assert not up_to_date(None, item)


# --------------------------------------------------------------------------------------
# Runs against the fixtures (replay transport)
# --------------------------------------------------------------------------------------


def _documents(acceptance: Acceptance) -> dict[str, Document]:
    with acceptance.db.session() as session, read_transaction(session):
        rows = session.scalars(select(Document)).all()
        for row in rows:
            session.expunge(row)
        return {row.url or row.id: row for row in rows}


def test_an_incremental_run_collects_documents_ministry_page_and_microsites(
    acceptance: Acceptance,
) -> None:
    run_id = acceptance.run(C4, C4)
    row = acceptance.run_row(run_id)
    assert row["status"] == "partial" and not row["complete_listing"]
    documents = _documents(acceptance)
    ministry = documents["https://thedigital.gov.ua/ministry"]
    assert (ministry.doc_type, ministry.license, ministry.extraction_method) == (
        "other",
        "cc_by_4_0",
        "turbo-stream",
    )
    assert documents["https://2years.thedigital.gov.ua/"].license == "cc_by_4_0"
    assert documents["https://2025.thedigital.gov.ua/"].license == "unknown"
    links = [doc for doc in documents.values() if doc.extraction_method == "listing_only"]
    assert len(links) == 8  # 7 on documents page 106, 1 on /ministry
    assert all(doc.published_start is None and doc.source_record_at for doc in links)
    files = [doc for doc in documents.values() if "storage.thedigital.gov.ua" in (doc.url or "")]
    assert files and all(doc.text_hash is None and doc.license == "unknown" for doc in files)
    observations = acceptance.observations(C4)
    assert all("fetched" not in observations[key]["details"] for key in observations)
    news = [key for key in observations if key.startswith("news:")]
    assert len(news) == 12  # page 1 sighted (no article fixture), page 2 failed: stop


def test_a_full_run_reads_the_oldest_page_and_its_article(acceptance: Acceptance) -> None:
    run_id = acceptance.run(C4, C4, mode="full")
    assert not acceptance.run_row(run_id)["complete_listing"]  # 363 pages have no fixture
    documents = _documents(acceptance)
    slug = "komanda-ministrerstva-prezentuvala-proekty-tsyfrovoi-osvity"
    news = documents[f"{SITE}/news/education/{slug}"]
    assert (news.doc_type, news.language, news.published_start, news.published_precision) == (
        "news",
        "uk",
        "2019-10-11",
        "day",
    )
    assert news.published_text == "2019-10-11T13:21:00+03:00"
    assert news.published_at_utc == "2019-10-11T10:21:00.000000Z"
    assert news.source_id == C4 and news.external_id
    observation = acceptance.observations(C4)[f"news:{slug}"]
    assert observation["details"]["published_at"] == "2019-10-11T13:21:00+03:00"
