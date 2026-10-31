"""The raw snapshot store (docs/COLLECTORS.md §5, docs/DATA_MODEL.md §14.1).

Every response body the app keeps (collector responses, manual fetches, uploads, replayed
fixtures) is stored once per content as ``<DATA_DIR>/raw/<sha256[0:2]>/<sha256>.gz``: gzip
level 6 with header mtime 0 and no file name, so equal bodies give equal files. A body is
streamed to a temporary file in ``<DATA_DIR>/raw`` while its SHA-256 and size are computed,
then linked into place unless that file exists (an existing file is never rewritten); only
then is the ``raw_snapshot`` row inserted, in its own small write unit, so no row points to a
missing file. Rows are immutable (append-only triggers).
"""

from __future__ import annotations

import codecs
import contextlib
import gzip
import hashlib
import os
import secrets
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from mdt.collectors.base import Snapshot
from mdt.db.models import RawSnapshot
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.clock import utc_now
from mdt.domain.ids import new_id

#: The response headers a snapshot keeps (never cookies or request headers).
KEPT_HEADERS = (
    "content-type",
    "content-length",
    "content-encoding",
    "content-language",
    "content-disposition",
    "etag",
    "last-modified",
    "cache-control",
    "date",
)
GZIP_LEVEL = 6
_CHUNK = 1 << 16
_HEAD_BYTES = 4096
_UTF8_BOM = codecs.BOM_UTF8
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OCTET_STREAM = "application/octet-stream"


class StoreError(RuntimeError):
    """A snapshot or its body file cannot be read."""


@dataclass(frozen=True)
class SnapshotMeta:
    """What is known about a body besides its bytes."""

    source_id: str
    via: str
    run_id: str | None = None
    url: str | None = None
    final_url: str | None = None
    redirects: Sequence[str] = ()
    http_status: int | None = None
    fetched_at: str | None = None  # default: now
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: str | None = None  # default: the media type of the Content-Type header
    filename: str | None = None


@dataclass(frozen=True)
class SnapshotRecord:
    """A ``raw_snapshot`` row without its body."""

    id: str
    run_id: str | None
    source_id: str
    via: str
    url: str | None
    final_url: str | None
    redirects: tuple[str, ...]
    http_status: int | None
    fetched_at: str
    headers: Mapping[str, str]
    content_type: str | None
    filename: str | None
    sha256: str
    size: int

    def with_body(self, body: bytes) -> Snapshot:
        """The parser input: this record plus its body."""
        return Snapshot(
            raw_snapshot_id=self.id,
            run_id=self.run_id,
            source_id=self.source_id,
            via=self.via,
            url=self.url,
            final_url=self.final_url,
            redirects=self.redirects,
            http_status=self.http_status,
            fetched_at=self.fetched_at,
            headers=self.headers,
            content_type=self.content_type,
            filename=self.filename,
            sha256=self.sha256,
            size=self.size,
            body=body,
        )

    def as_api(self) -> dict[str, Any]:
        """The ``Snapshot`` object of docs/API.md §7.3."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "via": self.via,
            "url": self.url,
            "final_url": self.final_url,
            "redirects": list(self.redirects),
            "http_status": self.http_status,
            "fetched_at": self.fetched_at,
            "headers": dict(self.headers),
            "content_type": self.content_type,
            "filename": self.filename,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass
class BodyFacts:
    """What one pass over an upload learns for its content type (docs/COLLECTORS.md §5)."""

    head: bytes = b""
    utf8_valid: bool = True
    decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")()
    )

    def feed(self, chunk: bytes) -> None:
        if len(self.head) < _HEAD_BYTES:
            self.head += chunk[: _HEAD_BYTES - len(self.head)]
        if self.utf8_valid:
            try:
                self.decoder.decode(chunk)
            except UnicodeDecodeError:
                self.utf8_valid = False

    def finish(self) -> None:
        if self.utf8_valid:
            try:
                self.decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                self.utf8_valid = False


def media_type(value: str | None) -> str | None:
    """``text/html; charset=utf-8`` → ``text/html`` (lower-case), or None."""
    if not value:
        return None
    kind = value.split(";", 1)[0].strip().lower()
    return kind or None


def kept_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """The response headers a snapshot keeps, with lower-case names."""
    lowered = {name.lower(): value for name, value in headers.items()}
    return {name: lowered[name] for name in KEPT_HEADERS if name in lowered}


def base_name(filename: str) -> str:
    """The base name of an uploaded file name (path parts of either style dropped)."""
    return PureWindowsPath(PurePosixPath(filename.strip()).name).name


def upload_content_type(filename: str | None, facts: BodyFacts, zip_names: set[str]) -> str:
    """Content type of an upload from its name and first bytes (docs/COLLECTORS.md §5)."""
    head = facts.head
    extension = Path(filename or "").suffix.lower()
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"PK\x03\x04"):
        if "word/document.xml" in zip_names:
            return DOCX
        if "xl/workbook.xml" in zip_names:
            return XLSX
        return OCTET_STREAM
    utf16 = head.startswith(_UTF16_BOMS)
    if utf16:
        text = head.decode("utf-16", errors="ignore")
    else:
        text = head.removeprefix(_UTF8_BOM).decode("utf-8", errors="ignore")
    if text.lstrip("\ufeff").lstrip().startswith("<"):
        return "text/html"
    if facts.utf8_valid or utf16:
        return "text/csv" if extension == ".csv" else "text/plain"
    return OCTET_STREAM


class SnapshotStore:
    """Content-addressed body files under ``raw_dir`` plus the ``raw_snapshot`` rows."""

    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir

    def path_of(self, sha256: str) -> Path:
        """The body file of a SHA-256."""
        return self.raw_dir / sha256[:2] / f"{sha256}.gz"

    # ----------------------------------------------------------------------------------
    # Writing
    # ----------------------------------------------------------------------------------

    def write_body(
        self, chunks: Iterable[bytes], facts: BodyFacts | None = None
    ) -> tuple[str, int]:
        """Store a body file; return its SHA-256 and size. Equal bodies share one file."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.raw_dir / f".tmp-{secrets.token_hex(8)}.gz"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as raw:
                with gzip.GzipFile(
                    filename="", mode="wb", compresslevel=GZIP_LEVEL, fileobj=raw, mtime=0
                ) as compressed:
                    for chunk in chunks:
                        if not chunk:
                            continue
                        digest.update(chunk)
                        size += len(chunk)
                        compressed.write(chunk)
                        if facts is not None:
                            facts.feed(chunk)
                raw.flush()
                os.fsync(raw.fileno())
            sha256 = digest.hexdigest()
            target = self.path_of(sha256)
            target.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(FileExistsError):
                os.link(temporary, target)  # atomic, and never replaces an existing file
        finally:
            temporary.unlink(missing_ok=True)
        if facts is not None:
            facts.finish()
        return sha256, size

    def put(self, session: Session, body: bytes, meta: SnapshotMeta) -> Snapshot:
        """Store ``body`` and insert its row; return the parser input."""
        sha256, size = self.write_body([body])
        return self.insert_row(session, sha256, size, meta).with_body(body)

    def put_upload(
        self, session: Session, chunks: Iterable[bytes], filename: str
    ) -> SnapshotRecord:
        """Stream an upload into the store (``via = upload``, ``source_id = manual``); its
        content type comes from the file name and the bytes (docs/COLLECTORS.md §5)."""
        facts = BodyFacts()
        sha256, size = self.write_body(chunks, facts)
        name = base_name(filename)
        zip_names = self._zip_names(sha256) if facts.head.startswith(b"PK\x03\x04") else set()
        meta = SnapshotMeta(
            source_id="manual",
            via="upload",
            filename=name,
            content_type=upload_content_type(name, facts, zip_names),
        )
        return self.insert_row(session, sha256, size, meta)

    def insert_row(
        self, session: Session, sha256: str, size: int, meta: SnapshotMeta
    ) -> SnapshotRecord:
        """Insert the ``raw_snapshot`` row of a stored body (its own write unit)."""
        headers = kept_headers(meta.headers)
        record = SnapshotRecord(
            id=new_id("raw"),
            run_id=meta.run_id,
            source_id=meta.source_id,
            via=meta.via,
            url=meta.url,
            final_url=meta.final_url,
            redirects=tuple(meta.redirects),
            http_status=meta.http_status,
            fetched_at=meta.fetched_at or utc_now(),
            headers=headers,
            content_type=meta.content_type or media_type(headers.get("content-type")),
            filename=meta.filename,
            sha256=sha256,
            size=size,
        )
        values = record.as_api()
        with write_transaction(session):
            session.execute(insert(RawSnapshot).values(**values))
        return record

    # ----------------------------------------------------------------------------------
    # Reading
    # ----------------------------------------------------------------------------------

    def read_body(self, sha256: str) -> bytes:
        """The decompressed body of a SHA-256."""
        try:
            with gzip.open(self.path_of(sha256), "rb") as file:
                return file.read()
        except (OSError, EOFError) as exc:
            raise StoreError(f"the body file of {sha256} cannot be read") from exc

    def iter_body(self, sha256: str) -> Iterator[bytes]:
        """The decompressed body in chunks (for streaming responses)."""
        try:
            with gzip.open(self.path_of(sha256), "rb") as file:
                while chunk := file.read(_CHUNK):
                    yield chunk
        except (OSError, EOFError) as exc:
            raise StoreError(f"the body file of {sha256} cannot be read") from exc

    def record(self, session: Session, raw_id: str) -> SnapshotRecord | None:
        """The row of ``raw_id`` (its own read transaction), or None."""
        with read_transaction(session):
            row = session.get(RawSnapshot, raw_id)
            return None if row is None else record_of(row)

    def open(self, session: Session, raw_id: str) -> Snapshot:
        """The snapshot ``raw_id`` with its body."""
        record = self.record(session, raw_id)
        if record is None:
            raise StoreError(f"unknown snapshot {raw_id}")
        return record.with_body(self.read_body(record.sha256))

    def latest_for_url(
        self, session: Session, url: str, *, via: str | None = None, status: int | None = None
    ) -> SnapshotRecord | None:
        """The newest snapshot of a requested URL, optionally of one ``via`` and status."""
        query = select(RawSnapshot).where(RawSnapshot.url == url)
        if via is not None:
            query = query.where(RawSnapshot.via == via)
        if status is not None:
            query = query.where(RawSnapshot.http_status == status)
        query = query.order_by(RawSnapshot.fetched_at.desc(), RawSnapshot.id.desc()).limit(1)
        with read_transaction(session):
            row = session.scalars(query).first()
            return None if row is None else record_of(row)

    def _zip_names(self, sha256: str) -> set[str]:
        try:
            with gzip.open(self.path_of(sha256), "rb") as file, zipfile.ZipFile(file) as archive:
                return set(archive.namelist())
        except (OSError, EOFError, zipfile.BadZipFile):
            return set()

    # ----------------------------------------------------------------------------------
    # Integrity (mdt check, DATA_MODEL §13)
    # ----------------------------------------------------------------------------------

    def check_files(self, session: Session, *, deep: bool = False) -> list[str]:
        """Problems with the body files: missing, another size than recorded (read from
        the gzip trailer), or with ``deep`` another SHA-256 or size after re-hashing."""
        problems: list[str] = []
        with read_transaction(session):
            rows = session.execute(
                select(RawSnapshot.id, RawSnapshot.sha256, RawSnapshot.size).order_by(
                    RawSnapshot.id
                )
            ).all()
        checked: dict[str, str | None] = {}
        for raw_id, sha256, size in rows:
            key = f"{sha256}:{size}"
            if key not in checked:
                checked[key] = self._file_problem(sha256, size, deep=deep)
            problem = checked[key]
            if problem is not None:
                problems.append(f"raw_snapshot {raw_id}: {problem}")
        return problems

    def _file_problem(self, sha256: str, size: int, *, deep: bool) -> str | None:
        path = self.path_of(sha256)
        if not path.is_file():
            return f"body file {path.name} is missing"
        if deep:
            digest = hashlib.sha256()
            length = 0
            try:
                for chunk in self.iter_body(sha256):
                    digest.update(chunk)
                    length += len(chunk)
            except StoreError:
                return f"body file {path.name} cannot be decompressed"
            if length != size:
                return f"body file {path.name} holds {length} bytes, the row says {size}"
            if digest.hexdigest() != sha256:
                return f"body file {path.name} does not match its SHA-256"
            return None
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            if file.tell() < 18:
                return f"body file {path.name} is not a gzip file"
            file.seek(-4, os.SEEK_END)
            trailer_size = int.from_bytes(file.read(4), "little")
        if trailer_size != size % (1 << 32):
            return f"body file {path.name} holds {trailer_size} bytes, the row says {size}"
        return None


def record_of(row: RawSnapshot) -> SnapshotRecord:
    """The record of an ORM row."""
    return SnapshotRecord(
        id=row.id,
        run_id=row.run_id,
        source_id=row.source_id,
        via=row.via,
        url=row.url,
        final_url=row.final_url,
        redirects=tuple(row.redirects or ()),
        http_status=row.http_status,
        fetched_at=row.fetched_at,
        headers=dict(row.headers or {}),
        content_type=row.content_type,
        filename=row.filename,
        sha256=row.sha256,
        size=row.size,
    )
