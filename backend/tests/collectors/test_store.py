"""The raw snapshot store (docs/COLLECTORS.md §5, docs/DATA_MODEL.md §14.1)."""

from __future__ import annotations

import gzip
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from mdt.collectors.store import (
    DOCX,
    OCTET_STREAM,
    PDF,
    XLSX,
    SnapshotMeta,
    SnapshotStore,
    StoreError,
    base_name,
    kept_headers,
    media_type,
)
from tests.conftest import Db


@pytest.fixture
def store(db: Db) -> SnapshotStore:
    return SnapshotStore(db.settings.raw_path)


def test_put_writes_a_content_addressed_gzip_file_and_a_row(db: Db, store: SnapshotStore) -> None:
    body = "Синтетичний приклад: example body\n".encode()
    sha256 = hashlib.sha256(body).hexdigest()
    with db.session() as session:
        snapshot = store.put(
            session,
            body,
            SnapshotMeta(
                source_id="example",
                via="live",
                url="https://example.org/page",
                final_url="https://example.org/page",
                http_status=200,
                headers={
                    "Content-Type": "text/html; charset=UTF-8",
                    "Set-Cookie": "session=1",
                    "ETag": '"abc"',
                    "X-Other": "dropped",
                },
            ),
        )
    path = db.settings.raw_path / sha256[:2] / f"{sha256}.gz"
    assert path.is_file()
    assert gzip.decompress(path.read_bytes()) == body
    raw = path.read_bytes()
    assert raw[:2] == b"\x1f\x8b"
    assert raw[4:8] == b"\x00\x00\x00\x00"  # header mtime 0
    assert raw[3] & 0x08 == 0  # no file name
    assert snapshot.sha256 == sha256 and snapshot.size == len(body) and snapshot.body == body
    assert snapshot.raw_snapshot_id.startswith("raw_")
    assert snapshot.content_type == "text/html"
    assert dict(snapshot.headers) == {"content-type": "text/html; charset=UTF-8", "etag": '"abc"'}
    with db.session() as session:
        reopened = store.open(session, snapshot.raw_snapshot_id)
    assert reopened == snapshot
    assert list(db.settings.raw_path.glob(".tmp-*")) == []


def test_equal_bodies_share_one_file_but_get_their_own_rows(db: Db, store: SnapshotStore) -> None:
    meta = SnapshotMeta(source_id="example", via="live", url="https://example.org/")
    with db.session() as session:
        first = store.put(session, b"same body", meta)
        path = store.path_of(first.sha256)
        mtime = path.stat().st_mtime_ns
        second = store.put(session, b"same body", meta)
    assert first.raw_snapshot_id != second.raw_snapshot_id
    assert first.sha256 == second.sha256
    assert path.stat().st_mtime_ns == mtime  # never rewritten
    files = list(db.settings.raw_path.rglob("*.gz"))
    assert files == [path]


def test_equal_bodies_give_equal_files(tmp_path: Path) -> None:
    one, two = SnapshotStore(tmp_path / "a"), SnapshotStore(tmp_path / "b")
    body = b"x" * 10_000
    sha_one, _ = one.write_body([body])
    sha_two, _ = two.write_body([body[:3], body[3:]])
    assert sha_one == sha_two
    assert one.path_of(sha_one).read_bytes() == two.path_of(sha_two).read_bytes()


def test_rows_are_immutable(db: Db, store: SnapshotStore) -> None:
    with db.session() as session:
        snapshot = store.put(session, b"body", SnapshotMeta(source_id="example", via="live"))
    with pytest.raises(sa.exc.DatabaseError, match="append-only"), db.engine.begin() as connection:
        connection.execute(
            text("UPDATE raw_snapshot SET via = 'upload' WHERE id = :id"),
            {"id": snapshot.raw_snapshot_id},
        )


def test_latest_for_url_filters_by_via_and_status(db: Db, store: SnapshotStore) -> None:
    url = "https://example.org/listing"
    with db.session() as session:
        store.put(
            session,
            b"old",
            SnapshotMeta(
                source_id="example",
                via="live",
                url=url,
                http_status=200,
                fetched_at="2026-10-01T00:00:00.000000Z",
            ),
        )
        newest_live = store.put(
            session,
            b"new",
            SnapshotMeta(
                source_id="example",
                via="live",
                url=url,
                http_status=200,
                fetched_at="2026-10-02T00:00:00.000000Z",
            ),
        )
        store.put(
            session,
            b"error",
            SnapshotMeta(
                source_id="example",
                via="live",
                url=url,
                http_status=500,
                fetched_at="2026-10-03T00:00:00.000000Z",
            ),
        )
        store.put(
            session,
            b"fixture",
            SnapshotMeta(
                source_id="example",
                via="replay",
                url=url,
                http_status=200,
                fetched_at="2026-10-04T00:00:00.000000Z",
            ),
        )
        assert store.latest_for_url(session, url).http_status == 200  # type: ignore[union-attr]
        latest = store.latest_for_url(session, url, via="live", status=200)
        assert latest is not None and latest.id == newest_live.raw_snapshot_id
        assert store.latest_for_url(session, "https://example.org/other") is None


def test_open_unknown_and_missing_files(db: Db, store: SnapshotStore) -> None:
    with db.session() as session:
        with pytest.raises(StoreError, match="unknown snapshot"):
            store.open(session, "raw_unknown")
        snapshot = store.put(session, b"body", SnapshotMeta(source_id="example", via="live"))
        store.path_of(snapshot.sha256).unlink()
        with pytest.raises(StoreError, match="cannot be read"):
            store.open(session, snapshot.raw_snapshot_id)


def test_check_files_reports_missing_and_changed_files(db: Db, store: SnapshotStore) -> None:
    with db.session() as session:
        intact = store.put(session, b"intact body", SnapshotMeta(source_id="x", via="live"))
        missing = store.put(session, b"missing body", SnapshotMeta(source_id="x", via="live"))
        resized = store.put(session, b"resized body", SnapshotMeta(source_id="x", via="live"))
        rehashed = store.put(session, b"rehashed body", SnapshotMeta(source_id="x", via="live"))
    store.path_of(missing.sha256).unlink()
    store.path_of(resized.sha256).write_bytes(gzip.compress(b"another length"))
    # The same length but other bytes: only the deep check notices.
    store.path_of(rehashed.sha256).write_bytes(gzip.compress(b"REHASHED BODY"))
    with db.session() as session:
        shallow = store.check_files(session)
        deep = store.check_files(session, deep=True)
    assert any(missing.raw_snapshot_id in line and "missing" in line for line in shallow)
    assert any(resized.raw_snapshot_id in line and "holds 14 bytes" in line for line in shallow)
    assert not any(rehashed.raw_snapshot_id in line for line in shallow)
    assert any(rehashed.raw_snapshot_id in line and "SHA-256" in line for line in deep)
    assert not any(intact.raw_snapshot_id in line for line in deep)
    assert len(deep) == 3


def _docx_bytes(entry: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(entry, "<document/>")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "body", "expected"),
    [
        ("report.pdf", b"%PDF-1.7\n...", PDF),
        ("letter.docx", _docx_bytes("word/document.xml"), DOCX),
        ("table.xlsx", _docx_bytes("xl/workbook.xml"), XLSX),
        ("archive.zip", _docx_bytes("other.xml"), OCTET_STREAM),
        ("page.html", b"\xef\xbb\xbf  \n<!doctype html><title>Example</title>", "text/html"),
        ("page.htm", " <html></html>".encode("utf-16"), "text/html"),
        ("notes.txt", "Синтетичний текст".encode(), "text/plain"),
        ("data.csv", b"slug,notes\nexample,Example note\n", "text/csv"),
        ("utf16.txt", "Example text".encode("utf-16"), "text/plain"),
        ("image.png", b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe", OCTET_STREAM),
        ("latin1.txt", "Beispiel für Text".encode("latin-1"), OCTET_STREAM),
    ],
)
def test_upload_content_types(
    db: Db, store: SnapshotStore, filename: str, body: bytes, expected: str
) -> None:
    chunks = [body[i : i + 7] for i in range(0, len(body), 7)]
    with db.session() as session:
        record = store.put_upload(session, iter(chunks), f"C:\\Users\\example\\{filename}")
    assert record.content_type == expected
    assert record.filename == filename
    assert (record.via, record.source_id, record.url, record.http_status) == (
        "upload",
        "manual",
        None,
        None,
    )
    assert store.read_body(record.sha256) == body


def test_header_and_name_helpers() -> None:
    assert media_type("Text/HTML; charset=utf-8") == "text/html"
    assert media_type(None) is None and media_type(" ; x") is None
    assert kept_headers({"Date": "d", "Cookie": "c", "content-length": "3"}) == {
        "content-length": "3",
        "date": "d",
    }
    assert base_name("../../etc/passwd") == "passwd"
    assert base_name("C:\\temp\\report.pdf") == "report.pdf"
