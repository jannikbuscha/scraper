"""Manual documents: uploads, fetches, archived copies and the create path
(documents/manual.py, docs/COLLECTORS.md §10, docs/DATA_MODEL.md §17.2).

Every URL uses a reserved example host; fetches go through ``httpx2.MockTransport``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2
import pytest
from sqlalchemy import select

from mdt.collectors.errors import CollectorUnavailableError, FetchFailedError
from mdt.collectors.replay import ReplayTransport
from mdt.collectors.store import SnapshotMeta, SnapshotStore
from mdt.collectors.throttle import HostThrottle
from mdt.config import Settings
from mdt.db.models import DocumentText, FetchLog, RawSnapshot
from mdt.db.session import read_transaction
from mdt.documents.manual import (
    ArchivedCopy,
    create_manual_document,
    fetch_document,
    parse_capture_url,
    store_upload,
)
from mdt.domain.actor import Actor
from mdt.domain.errors import UniqueViolationError, ValidationError
from mdt.domain.records import field_meta_of, load_row
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.revisions import apply_change
from tests.collectors.conftest import FIXTURES, TEST_EMAIL, FakeClock, Site
from tests.conftest import Db, make_settings
from tests.documents.helpers import blank_pdf, docx_bytes
from tests.parsing.helpers import fixture_bytes

PAGE = "https://example.org/reports/annual"
HTML = (
    "<html><head><title>Example annual report</title></head>"
    "<body><h1>Example annual report</h1>"
    "<p>Це приклад тексту звіту для перевірки. Він написаний українською мовою, щоб мова тексту"
    " визначалася правильно навіть разом з англійською назвою сторінки.</p></body>"
    "</html>"
).encode()


@pytest.fixture
def settings(db: Db, codebook_dir: Path, seed_dir: Path) -> Settings:
    """The test database's settings with a usable contact address."""
    return make_settings(db.root, codebook_dir, seed_dir, contact_email=TEST_EMAIL)


def _fetch(db: Db, settings: Settings, url: str, site: Site) -> tuple[Any, Any]:
    with db.session() as session:
        return fetch_document(
            session,
            settings,
            url,
            transport=httpx2.MockTransport(site),
            clock=FakeClock(),
            throttle=HostThrottle(),
        )


def _document(db: Db, document_id: str) -> dict[str, Any]:
    with db.session() as session, read_transaction(session):
        row = load_row(session, ENTITY_TYPES["document"], document_id)
        assert row is not None
        return {**row, "field_meta": field_meta_of(ENTITY_TYPES["document"], row)}


def _text(db: Db, text_hash: str) -> str:
    with db.session() as session, read_transaction(session):
        return str(
            session.scalar(select(DocumentText.text).where(DocumentText.text_hash == text_hash))
        )


# Uploads ------------------------------------------------------------------------------


def test_an_html_upload_is_stored_and_suggests_values(db: Db, settings: Settings) -> None:
    with db.session() as session:
        record, suggested = store_upload(
            session, settings, [HTML[:40], HTML[40:]], "dir/report.html"
        )
    assert (record.via, record.source_id, record.run_id) == ("upload", "manual", None)
    assert (record.filename, record.content_type) == ("report.html", "text/html")
    assert suggested.title == "Example annual report"
    assert suggested.language == "uk"
    assert (suggested.publisher, suggested.extraction_method) == (None, "html")
    assert suggested.char_count > 0 and suggested.warnings == ()


@pytest.mark.parametrize(
    ("filename", "body", "title", "method", "warnings"),
    [
        ("Звіт про приклад.pdf", blank_pdf(), "Звіт про приклад", "pdf", ["no_text_layer"]),
        (
            "scan.pdf",
            blank_pdf(title="Example scanned report"),
            "Example scanned report",
            "pdf",
            ["no_text_layer"],
        ),
        (
            "example.docx",
            docx_bytes("<w:p><w:r><w:t>Example text</w:t></w:r></w:p>", title="Example memo"),
            "Example memo",
            "docx",
            [],
        ),
        ("notes.txt", b"Example notes", "notes", "txt", []),
        ("photo.png", b"\x89PNG\r\n\x1a\nexample", "photo", "none", ["no_text"]),
        ("legacy.txt", "Приклад".encode("cp1251"), "legacy", "txt", ["unsupported_encoding"]),
    ],
)
def test_suggested_values_per_file_type(
    db: Db,
    settings: Settings,
    filename: str,
    body: bytes,
    title: str,
    method: str,
    warnings: list[str],
) -> None:
    with db.session() as session:
        _, suggested = store_upload(session, settings, [body], filename)
    assert suggested.title == title
    assert suggested.extraction_method == method
    assert [warning.code for warning in suggested.warnings] == warnings
    assert suggested.as_api()["warnings"] == [
        {"code": warning.code, "message": warning.message, "field": None}
        for warning in suggested.warnings
    ]


def test_the_pdf_fixture_upload_suggests_the_file_name_as_title(db: Db, settings: Settings) -> None:
    body = fixture_bytes("ministry_news", "storage_pdf_draft_resolution.pdf")
    with db.session() as session:
        _, suggested = store_upload(session, settings, [body], "draft-resolution.pdf")
    assert suggested.title == "draft-resolution"
    assert suggested.language == "uk"
    assert suggested.extraction_method == "pdf" and suggested.char_count > 0


def test_an_upload_needs_a_file_name(db: Db, settings: Settings) -> None:
    with db.session() as session, pytest.raises(ValidationError) as error:
        store_upload(session, settings, [b"x"], " / ")
    assert error.value.details == {"filename": ["must name a file"]}


# Creating from an upload --------------------------------------------------------------


def _upload(db: Db, settings: Settings, body: bytes, filename: str) -> str:
    with db.session() as session:
        record, _ = store_upload(session, settings, [body], filename)
    return record.id


def test_a_document_from_an_upload(db: Db, settings: Settings) -> None:
    snapshot_id = _upload(db, settings, HTML, "report.html")
    values = {
        "snapshot_id": snapshot_id,
        "title": "Example annual report",
        "url": "https://example.org/reports/annual.html",
        "retrieved_at": "2026-10-30T10:00:00Z",
        "language": "lang_a",
        "doc_type": "doc_a",
        "published": "2025",
        "published_basis": "stated_in_source",
    }
    with db.session() as session:
        created = create_manual_document(session, settings, values, note="Example note")
    assert created.warnings == ()
    document = _document(db, created.result.entity_id)
    assert document["source_id"] == "manual"
    assert document["raw_snapshot_id"] == snapshot_id
    assert document["extraction_method"] == "html"
    assert document["retrieved_at"] == "2026-10-30T10:00:00.000000Z"
    assert document["canonical_url"] == "https://example.org/reports/annual.html"
    assert document["screening_status"] == "unscreened"
    assert document["verification_status"] == "unverified"
    assert document["created_by"] == "user"
    assert _text(db, document["text_hash"]).startswith("Example annual report")
    meta = document["field_meta"]
    assert meta["title"]["src"] == "manual" and meta["title"]["locked"] is True
    assert meta["source_id"]["src"] == "manual"


def test_an_upload_without_text_creates_a_document_without_text(db: Db, settings: Settings) -> None:
    snapshot_id = _upload(db, settings, blank_pdf(), "scan.pdf")
    with db.session() as session:
        created = create_manual_document(
            session, settings, {"snapshot_id": snapshot_id, "title": "Example scan"}
        )
    assert [warning.code for warning in created.warnings] == ["no_text_layer"]
    document = _document(db, created.result.entity_id)
    assert (document["text_hash"], document["extraction_method"]) == (None, "pdf")


def test_an_upload_with_a_url_needs_a_retrieval_time(db: Db, settings: Settings) -> None:
    snapshot_id = _upload(db, settings, HTML, "report.html")
    values = {"snapshot_id": snapshot_id, "title": "Example", "url": "https://example.org/a"}
    with db.session() as session, pytest.raises(ValidationError) as error:
        create_manual_document(session, settings, values)
    assert "retrieved_at" in (error.value.details or {})


def test_an_unsupported_text_encoding_is_refused_on_create(db: Db, settings: Settings) -> None:
    snapshot_id = _upload(db, settings, "Приклад".encode("cp1251"), "legacy.txt")
    with db.session() as session, pytest.raises(ValidationError) as error:
        create_manual_document(session, settings, {"snapshot_id": snapshot_id, "title": "Example"})
    assert error.value.details == {"snapshot_id": ["the text file is not UTF-8"]}


def test_the_canonical_url_must_be_unused(db: Db, settings: Settings) -> None:
    with db.session() as session:
        apply_change(
            session,
            "document",
            None,
            {
                "title": "Example",
                "url": "https://Example.org/a/",
                "retrieved_at": "2026-10-30T10:00:00Z",
            },
            Actor.ui(),
        )
    snapshot_id = _upload(db, settings, HTML, "report.html")
    values = {
        "snapshot_id": snapshot_id,
        "title": "Example",
        "url": "https://example.org/a",
        "retrieved_at": "2026-10-30T10:00:00Z",
    }
    with db.session() as session, pytest.raises(UniqueViolationError):
        create_manual_document(session, settings, values)


@pytest.mark.parametrize("snapshot_id", ["raw_unknown", "", None])
def test_unknown_snapshots_are_refused(db: Db, settings: Settings, snapshot_id: Any) -> None:
    with db.session() as session, pytest.raises(ValidationError) as error:
        create_manual_document(session, settings, {"snapshot_id": snapshot_id, "title": "Example"})
    assert "snapshot_id" in (error.value.details or {})


def test_collector_snapshots_are_not_manual(db: Db, settings: Settings) -> None:
    with db.session() as session:
        snapshot = SnapshotStore(settings.raw_path).put(
            session,
            HTML,
            SnapshotMeta(source_id="ministry_news", via="live", url=PAGE, http_status=200),
        )
        with pytest.raises(ValidationError) as error:
            create_manual_document(
                session, settings, {"snapshot_id": snapshot.raw_snapshot_id, "title": "Example"}
            )
    assert error.value.details == {"snapshot_id": ["is not a manual upload or fetch"]}


# Fetching a URL ---------------------------------------------------------------------


def test_a_fetched_page_becomes_a_document_with_its_url_and_fetch_time(
    db: Db, settings: Settings
) -> None:
    site = Site({PAGE: httpx2.Response(200, content=HTML, headers={"content-type": "text/html"})})
    record, suggested = _fetch(db, settings, PAGE, site)
    assert (record.via, record.source_id, record.run_id, record.url) == (
        "live",
        "manual",
        None,
        PAGE,
    )
    assert (suggested.publisher, suggested.title) == ("example.org", "Example annual report")
    with db.session() as session:
        created = create_manual_document(
            session,
            settings,
            {"snapshot_id": record.id, "title": suggested.title, "language": "lang_a"},
        )
        with read_transaction(session):
            fetches = [
                (row.purpose, row.run_id)
                for row in session.scalars(select(FetchLog).order_by(FetchLog.id))
            ]
    document = _document(db, created.result.entity_id)
    assert (document["url"], document["retrieved_at"]) == (PAGE, record.fetched_at)
    assert document["archive_urls"] == []
    assert fetches == [("robots", None), ("content", None)]


def test_url_and_retrieval_time_of_a_fetched_snapshot_are_not_given(
    db: Db, settings: Settings
) -> None:
    site = Site({PAGE: httpx2.Response(200, content=HTML, headers={"content-type": "text/html"})})
    record, _ = _fetch(db, settings, PAGE, site)
    values = {
        "snapshot_id": record.id,
        "title": "Example",
        "url": PAGE,
        "retrieved_at": "2026-10-30T10:00:00Z",
    }
    with db.session() as session, pytest.raises(ValidationError) as error:
        create_manual_document(session, settings, values)
    assert set(error.value.details or {}) == {"url", "retrieved_at"}


def test_an_existing_canonical_url_is_refused_before_fetching(db: Db, settings: Settings) -> None:
    with db.session() as session:
        apply_change(
            session,
            "document",
            None,
            {"title": "Example", "url": PAGE + "/", "retrieved_at": "2026-10-30T10:00:00Z"},
            Actor.ui(),
        )
    site = Site({PAGE: httpx2.Response(200, content=HTML)})
    with pytest.raises(UniqueViolationError) as error:
        _fetch(db, settings, PAGE + "#part", site)
    assert error.value.details is not None and error.value.details["existing"]["label"] == "Example"
    assert site.requests == []


def test_fetch_failures_and_the_contact_address(
    db: Db, settings: Settings, codebook_dir: Path, seed_dir: Path
) -> None:
    with pytest.raises(FetchFailedError) as error:
        _fetch(db, settings, PAGE, Site({PAGE: 404}))
    assert error.value.details == {"reason": "http_error", "status": 404}
    robots = Site({"https://example.org/robots.txt": "User-agent: *\nDisallow: /reports/\n"})
    with pytest.raises(FetchFailedError) as error:
        _fetch(db, settings, PAGE, robots)
    assert error.value.details == {"reason": "robots_disallowed", "status": None}
    no_contact = make_settings(db.root, codebook_dir, seed_dir)
    with pytest.raises(CollectorUnavailableError):
        _fetch(db, no_contact, PAGE, Site())
    with db.session() as session, pytest.raises(ValidationError):
        fetch_document(session, settings, "ftp://example.org/file")


# Archived copies -----------------------------------------------------------------------

CAPTURE = "https://web.archive.org/web/20200101000000/https://example.org/old/page"
ID_FORM = "https://web.archive.org/web/20200101000000id_/https://example.org/old/page"
NEAREST = "https://web.archive.org/web/20191231120000id_/https://example.org/old/page"


def test_capture_urls() -> None:
    assert parse_capture_url(CAPTURE) == ArchivedCopy(
        "20200101000000", "https://example.org/old/page"
    )
    copy = parse_capture_url(ID_FORM)
    assert copy is not None and copy.fetch_url == ID_FORM
    assert copy.archive_url("20191231120000") == (
        "https://web.archive.org/web/20191231120000/https://example.org/old/page"
    )
    assert parse_capture_url("https://example.org/web/20200101000000/https://x.example") is None
    with pytest.raises(ValidationError):
        parse_capture_url("https://web.archive.org/web/20200101000000/example.org/old")


def _archive_site(**extra: Any) -> Site:
    return Site(
        {
            ID_FORM: httpx2.Response(302, headers={"location": NEAREST}),
            NEAREST: httpx2.Response(200, content=HTML, headers={"content-type": "text/html"}),
            **extra,
        }
    )


def test_an_archived_copy_is_fetched_in_its_id_form(db: Db, settings: Settings) -> None:
    site = _archive_site()
    record, suggested = _fetch(db, settings, CAPTURE, site)
    assert record.via == "wayback:20191231120000"  # the final URL's timestamp
    assert record.url == ID_FORM and record.final_url == NEAREST
    assert suggested.publisher == "example.org"
    # The live robots.txt of the original host was read (no stored one existed).
    assert "https://example.org/robots.txt" in site.urls()
    assert "https://example.org/old/page" not in site.urls()
    with db.session() as session:
        created = create_manual_document(
            session, settings, {"snapshot_id": record.id, "title": "Example"}
        )
    document = _document(db, created.result.entity_id)
    assert document["url"] == "https://example.org/old/page"
    assert document["archive_urls"] == [
        "https://web.archive.org/web/20191231120000/https://example.org/old/page"
    ]
    assert document["retrieved_at"] == record.fetched_at


def _store_robots(db: Db, settings: Settings, body: bytes, status: int = 200) -> None:
    with db.session() as session:
        SnapshotStore(settings.raw_path).put(
            session,
            body,
            SnapshotMeta(
                source_id="project_sites",
                via="live",
                url="https://example.org/robots.txt",
                http_status=status,
            ),
        )


def test_a_stored_robots_txt_decides_without_contacting_the_original_host(
    db: Db, settings: Settings
) -> None:
    _store_robots(db, settings, b"User-agent: *\nDisallow: /old/\n")
    site = _archive_site()
    with pytest.raises(FetchFailedError) as error:
        _fetch(db, settings, CAPTURE, site)
    assert error.value.details == {"reason": "robots_disallowed", "status": None}
    assert not [url for url in site.urls() if url.startswith("https://example.org/")]
    assert not [url for url in site.urls() if "id_" in url]


def test_an_unreadable_stored_robots_txt_falls_back_to_the_live_one(
    db: Db, settings: Settings
) -> None:
    _store_robots(db, settings, b"server error", status=500)
    site = _archive_site(**{"https://example.org/robots.txt": "User-agent: *\nAllow: /\n"})
    record, _ = _fetch(db, settings, CAPTURE, site)
    assert record.via == "wayback:20191231120000"
    assert "https://example.org/robots.txt" in site.urls()


def test_without_any_readable_robots_txt_the_copy_is_refused(db: Db, settings: Settings) -> None:
    site = _archive_site(**{"https://example.org/robots.txt": 500})
    with pytest.raises(FetchFailedError) as error:
        _fetch(db, settings, CAPTURE, site)
    assert error.value.details is not None and error.value.details["reason"] == "robots_unavailable"
    assert not [url for url in site.urls() if "id_" in url]


def test_fetched_snapshots_are_kept_as_raw_snapshots(db: Db, settings: Settings) -> None:
    record, _ = _fetch(db, settings, CAPTURE, _archive_site())
    with db.session() as session, read_transaction(session):
        row = session.get(RawSnapshot, record.id)
        assert row is not None and row.sha256 == record.sha256


def test_the_synthetic_capture_fixture_replays_as_an_archived_copy(
    db: Db, settings: Settings
) -> None:
    """``fixtures/wayback/synthetic_capture_redirected`` (docs/COLLECTORS.md §8.5, §10.3):
    the archive redirects the ``id_`` request to the nearest capture, whose timestamp names
    the document's archive URL. A replayed snapshot says ``via = replay`` (fixture content
    never claims a retrieval, §4.10)."""
    original = "https://example.org/projects/technologies/example-gamma"
    with db.session() as session:
        record, _ = fetch_document(
            session,
            settings,
            f"https://web.archive.org/web/20200102000000/{original}",
            transport=ReplayTransport([FIXTURES / "wayback"]),
            clock=FakeClock(),
            throttle=HostThrottle(),
        )
    assert record.via == "replay"
    assert record.final_url == f"https://web.archive.org/web/20200102030405id_/{original}"
    with db.session() as session:
        created = create_manual_document(
            session, settings, {"snapshot_id": record.id, "title": "Example project Gamma"}
        )
    document = _document(db, created.result.entity_id)
    assert document["url"] == original
    assert document["archive_urls"] == [f"https://web.archive.org/web/20200102030405/{original}"]
