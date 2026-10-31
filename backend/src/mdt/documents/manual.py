"""Manual documents (docs/COLLECTORS.md §10, docs/DATA_MODEL.md §17.2).

A manual document is always created from a stored snapshot: an upload (:func:`store_upload`)
or a fetch of a URL with the polite client (:func:`fetch_document`), which may be an archived
copy from the Wayback Machine. Both return **suggested values** derived from the file; only
what the person then submits is written (:func:`create_manual_document`, channel ``ui``,
``src = manual``). The domain layer sets the system fields of this create path: ``source_id
= manual``, ``raw_snapshot_id``, ``text_hash`` and ``extraction_method``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.collectors.base import Snapshot
from mdt.collectors.client import PoliteHttpClient, block_signature, manual_fetch_client
from mdt.collectors.errors import FetchFailedError
from mdt.collectors.parsing.language import detect_language
from mdt.collectors.robots import RobotsPolicy, policy_from_response
from mdt.collectors.sources import MANUAL
from mdt.collectors.store import SnapshotRecord, SnapshotStore, base_name
from mdt.collectors.throttle import Clock, HostThrottle
from mdt.collectors.urls import parse_fetch_url
from mdt.config import Settings
from mdt.db.models import Document, RawSnapshot
from mdt.db.session import read_transaction, write_transaction
from mdt.documents.extract import Extraction, ExtractionError, ExtractionWarning, extract_text
from mdt.domain.actor import Actor
from mdt.domain.document_versions import store_text
from mdt.domain.errors import UniqueViolationError, ValidationError
from mdt.domain.labels import ref_info
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.urls import UrlError, canonical_url, normalize_url
from mdt.domain.writes import ChangeResult, WriteUnit, clean_note, create_record, normalize_changes

#: The document fields a person submits on the create form (docs/API.md §7.8).
FORM_FIELDS = (
    "title",
    "url",
    "retrieved_at",
    "doc_type",
    "language",
    "publisher",
    "published",
    "published_basis",
    "published_text",
    "license",
)
WAYBACK_HOST = "web.archive.org"
#: ``https://web.archive.org/web/<14 digits>[<flag>_]/<original URL>``.
_CAPTURE = re.compile(
    r"^https?://web\.archive\.org/web/(?P<timestamp>\d{14})(?:[a-z]{2}_)?/(?P<original>.+)$",
    re.IGNORECASE,
)
_STORED_ROBOTS_LOOKBACK = 10


@dataclass(frozen=True)
class ArchivedCopy:
    """A Wayback capture URL: its timestamp, the original URL and the ``id_`` form that
    returns the original bytes (SOURCES S5)."""

    timestamp: str
    original: str

    @property
    def fetch_url(self) -> str:
        """The capture in its ``id_`` form."""
        return f"https://{WAYBACK_HOST}/web/{self.timestamp}id_/{self.original}"

    def archive_url(self, timestamp: str | None = None) -> str:
        """The capture page (``archive_urls``) for ``timestamp`` (default: the requested)."""
        return f"https://{WAYBACK_HOST}/web/{timestamp or self.timestamp}/{self.original}"


def parse_capture_url(url: str) -> ArchivedCopy | None:
    """The archived copy a Wayback capture URL names, or None for any other URL. The
    original URL must be an absolute http(s) URL."""
    match = _CAPTURE.match(url.strip())
    if match is None:
        return None
    original = match.group("original")
    if not original.lower().startswith(("http://", "https://")):
        raise ValidationError.single(
            "url", "a Wayback capture URL must contain the original URL with http:// or https://"
        )
    try:
        return ArchivedCopy(match.group("timestamp"), normalize_url(original))
    except UrlError as exc:
        raise ValidationError.single("url", str(exc)) from exc


@dataclass(frozen=True)
class Suggested:
    """The defaults the form offers (docs/API.md §7.7): never written by themselves."""

    title: str | None
    language: str | None
    publisher: str | None
    extraction_method: str
    char_count: int
    warnings: tuple[ExtractionWarning, ...] = ()

    def as_api(self) -> dict[str, Any]:
        """The ``Suggested`` object of the API."""
        return {
            "title": self.title,
            "language": self.language,
            "publisher": self.publisher,
            "extraction_method": self.extraction_method,
            "char_count": self.char_count,
            "warnings": [
                {"code": warning.code, "message": warning.message, "field": None}
                for warning in self.warnings
            ],
        }


def _file_stem(name: str | None) -> str | None:
    if not name:
        return None
    stem = PurePosixPath(name).stem.strip()
    return stem or None


def _url_file_name(url: str | None) -> str | None:
    if not url:
        return None
    return unquote(PurePosixPath(urlsplit(url).path).name) or None


def _extract(snapshot: Snapshot) -> Extraction:
    return extract_text(snapshot.body, snapshot.content_type, snapshot.filename)


def suggest(snapshot: Snapshot, *, publisher: str | None = None) -> Suggested:
    """Suggested values of a stored file: the HTML or metadata title, else the file name
    without extension; the language of title and text (docs/COLLECTORS.md §7.5); the
    extraction method, character count and warnings."""
    file_title = _file_stem(snapshot.filename or _url_file_name(snapshot.final_url or snapshot.url))
    try:
        extraction = _extract(snapshot)
    except ExtractionError as exc:
        warning = ExtractionWarning("unsupported_encoding", str(exc))
        return Suggested(file_title, None, publisher, "txt", 0, (warning,))
    title = extraction.title or file_title
    return Suggested(
        title=title,
        language=detect_language(title, extraction.text),
        publisher=publisher,
        extraction_method=extraction.method,
        char_count=extraction.char_count,
        warnings=extraction.warnings,
    )


def store_upload(
    session: Session, settings: Settings, chunks: Iterable[bytes], filename: str
) -> tuple[SnapshotRecord, Suggested]:
    """Store an upload (``via = upload``, ``source_id = manual``) and suggest values. The
    caller refuses an empty body and a missing file name (docs/API.md §7.7)."""
    name = base_name(filename)
    if not name:
        raise ValidationError.single("filename", "must name a file")
    store = SnapshotStore(settings.raw_path)
    record = store.put_upload(session, chunks, name)
    snapshot = record.with_body(store.read_body(record.sha256))
    return record, suggest(snapshot)


# --------------------------------------------------------------------------------------
# Fetching a URL (docs/COLLECTORS.md §10.3)
# --------------------------------------------------------------------------------------


def check_url_unused(session: Session, url: str) -> None:
    """409 ``unique_violation`` if a live document has the canonical URL of ``url``."""
    with read_transaction(session):
        existing = session.execute(
            select(Document.id).where(
                Document.canonical_url == canonical_url(url), Document.deleted_at.is_(None)
            )
        ).scalar()
        info = ref_info(session, existing) if existing else None
    if existing is not None:
        payload = {"id": info.id, "label": info.label, "deleted": info.deleted} if info else None
        raise UniqueViolationError("canonical_url", payload)


def _stored_robots(session: Session, store: SnapshotStore, robots_url: str) -> RobotsPolicy | None:
    """The newest stored robots.txt response of the origin that can be read (rules or
    allow all), or None."""
    with read_transaction(session):
        rows = session.execute(
            select(RawSnapshot.id)
            .where(RawSnapshot.url == robots_url)
            .order_by(RawSnapshot.fetched_at.desc(), RawSnapshot.id.desc())
            .limit(_STORED_ROBOTS_LOOKBACK)
        ).scalars()
        ids = list(rows)
    for raw_id in ids:
        snapshot = store.open(session, raw_id)
        challenge = block_signature(snapshot.http_status, snapshot.headers, snapshot.body)
        policy = policy_from_response(
            snapshot.http_status, snapshot.body, challenge=challenge is not None, snapshot_id=raw_id
        )
        if policy.state in ("rules", "allow_all"):
            return policy
    return None


def check_archive_robots(
    session: Session, store: SnapshotStore, client: PoliteHttpClient, original: str
) -> None:
    """Archived copies of robots-disallowed paths are never read (SOURCES §5 item 2): the
    newest readable stored robots.txt of the original's origin decides, else the live one;
    if neither can be read, the copy is refused (``robots_unavailable``)."""
    target = parse_fetch_url(original)
    policy = _stored_robots(session, store, target.robots_url) or client.robots_policy(original)
    if policy.state not in ("rules", "allow_all"):
        raise FetchFailedError("robots_unavailable", policy.status)
    if not policy.allows(target.url):
        raise FetchFailedError("robots_disallowed", None)


def _wayback_via(copy: ArchivedCopy) -> Callable[[str], str]:
    def via(final_url: str) -> str:
        final = _CAPTURE.match(final_url)
        return f"wayback:{final.group('timestamp') if final else copy.timestamp}"

    return via


def fetch_document(
    session: Session,
    settings: Settings,
    url: str,
    *,
    transport: httpx2.BaseTransport | None = None,
    clock: Clock | None = None,
    throttle: HostThrottle | None = None,
) -> tuple[SnapshotRecord, Suggested]:
    """Fetch ``url`` synchronously with the polite client (``source_id = manual``, no run,
    60 s budget) after checking that no live document has its canonical URL; a Wayback
    capture URL is fetched in its ``id_`` form as an archived copy (``via =
    wayback:<timestamp>``). Raises ``409 unique_violation``, ``409 collector_unavailable``
    (``CONTACT_EMAIL``) or ``502 fetch_failed``."""
    if not isinstance(url, str):
        raise ValidationError.single("url", "must be a string")
    try:
        requested = normalize_url(url)
    except UrlError as exc:
        raise ValidationError.single("url", str(exc)) from exc
    copy = parse_capture_url(requested)
    document_url = copy.original if copy else requested
    check_url_unused(session, document_url)
    store = SnapshotStore(settings.raw_path)
    with manual_fetch_client(
        session, settings, transport=transport, clock=clock, throttle=throttle
    ) as client:
        if copy is not None:
            check_archive_robots(session, store, client, copy.original)
            result = client.get(copy.fetch_url, conditional=False, via_for=_wayback_via(copy))
        else:
            result = client.get(requested, conditional=False)
    if not result.ok or result.snapshot is None:
        raise FetchFailedError(result.reason, result.status)
    record = store.record(session, result.snapshot.raw_snapshot_id)
    assert record is not None
    publisher = parse_fetch_url(document_url).host
    return record, suggest(result.snapshot, publisher=publisher)


# --------------------------------------------------------------------------------------
# Creating the document (docs/API.md §7.8)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualDocument:
    """The created document and the warnings of its text extraction."""

    result: ChangeResult
    warnings: tuple[ExtractionWarning, ...]

    def warnings_payload(self) -> list[dict[str, Any]]:
        """``warnings`` as in the API response."""
        return [
            {"code": warning.code, "message": warning.message, "field": None}
            for warning in self.warnings
        ] + self.result.warnings_payload()


def _manual_snapshot(session: Session, store: SnapshotStore, snapshot_id: Any) -> SnapshotRecord:
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValidationError.single("snapshot_id", "is required")
    record = store.record(session, snapshot_id)
    if record is None:
        raise ValidationError.single("snapshot_id", "names no stored snapshot")
    manual_via = record.via in ("upload", "live", "replay") or record.via.startswith("wayback:")
    if record.source_id != MANUAL or record.run_id is not None or not manual_via:
        raise ValidationError.single("snapshot_id", "is not a manual upload or fetch")
    return record


def _form_values(record: SnapshotRecord, values: Mapping[str, Any]) -> dict[str, Any]:
    form = {name: values[name] for name in FORM_FIELDS if name in values}
    if record.via == "upload":
        return form
    given = [name for name in ("url", "retrieved_at") if form.get(name) is not None]
    if given:
        raise ValidationError(
            {name: ["must not be given for a fetched snapshot"] for name in given}
        )
    copy = parse_capture_url(record.url or "")
    form["url"] = copy.original if copy else record.url
    form["retrieved_at"] = record.fetched_at
    if copy is not None:
        form["archive_urls"] = [copy.archive_url(_capture_timestamp(record, copy))]
    return form


def _capture_timestamp(record: SnapshotRecord, copy: ArchivedCopy) -> str:
    """The timestamp of the capture actually fetched: from ``via``, else from the final URL
    (a replayed fetch), else the requested one."""
    if record.via.startswith("wayback:"):
        return record.via.removeprefix("wayback:")
    final = _CAPTURE.match(record.final_url or "")
    return final.group("timestamp") if final else copy.timestamp


def create_manual_document(
    session: Session, settings: Settings, values: Mapping[str, Any], *, note: str | None = None
) -> ManualDocument:
    """Create a document from an upload or a fetched snapshot (``values`` = ``snapshot_id``
    plus the form fields) in one write unit on channel ``ui``."""
    store = SnapshotStore(settings.raw_path)
    record = _manual_snapshot(session, store, values.get("snapshot_id"))
    form = _form_values(record, values)
    try:
        extraction = extract_text(
            store.read_body(record.sha256), record.content_type, record.filename
        )
    except ExtractionError as exc:
        raise ValidationError.single("snapshot_id", str(exc)) from exc
    clean = clean_note(note)
    with write_transaction(session):
        unit = WriteUnit.open(session, ENTITY_TYPES["document"], Actor.ui())
        provided = normalize_changes(unit, form, creating=True)
        system: dict[str, Any] = {
            "source_id": MANUAL,
            "raw_snapshot_id": record.id,
            "extraction_method": extraction.method,
        }
        if extraction.text:
            system["text_hash"] = store_text(session, extraction.text, unit.ts)
        provided.update(normalize_changes(unit, system, creating=True, allow_system=True))
        result = create_record(unit, provided, note=clean, batch_id=None)
    return ManualDocument(result, extraction.warnings)
