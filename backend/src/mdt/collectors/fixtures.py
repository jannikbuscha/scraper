"""``mdt fixtures capture <collector>`` (docs/COLLECTORS.md §11): record a collector's
``fixtures`` list from ``sources.yaml`` through the polite client and write each body plus
``<name>.meta.json`` in the format of ``backend/tests/fixtures/README.md``.

Nothing is recorded in the database. Bodies are written whole, so a list may name only
openly licensed pages or technical responses (robots.txt, CDX JSON, sitemaps); a body above
1 MiB, or one that contains the contact address, the User-Agent product token, any e-mail
address or the kmu.gov.ua bot-manager token, is refused ("capture an excerpt by hand"). A
gzip body (a CDX answer without ``Content-Encoding``, written as ``.gz``) is checked
decompressed, the size limit included. The meta file never carries the User-Agent or the
contact address.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx2

from mdt import __version__
from mdt.collectors.client import PoliteHttpClient, user_agent
from mdt.collectors.fetchlog import MemorySink
from mdt.collectors.robots import PRODUCT_TOKEN
from mdt.collectors.sources import CollectorConfig
from mdt.collectors.store import kept_headers, media_type
from mdt.collectors.throttle import Clock
from mdt.config import REPO_ROOT, Settings
from mdt.domain.clock import utc_now

MAX_FIXTURE_BYTES = 1 << 20
GZIP_MAGIC = b"\x1f\x8b"
_EMAIL_RE = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_BOT_TOKEN = b"__uzdbm"
_EXTENSIONS = {
    "application/json": ".json",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "application/pdf": ".pdf",
}


@dataclass(frozen=True)
class CaptureResult:
    """What happened to one fixture of the list."""

    name: str
    state: str  # written, kept, failed, refused
    detail: str
    body_path: Path | None = None


def default_out_dir(settings: Settings, collector: str) -> Path:
    """``backend/tests/fixtures/<collector>/`` in a source checkout, else
    ``DATA_DIR/fixtures/<collector>/``."""
    fixtures = REPO_ROOT / "backend" / "tests" / "fixtures"
    if fixtures.is_dir():
        return fixtures / collector
    return settings.data_path / "fixtures" / collector


def extension_for(content_type: str | None, body: bytes) -> str:
    """The body file extension: by media type, ``.json`` for JSON sent as text, ``.gz``
    appended for a gzip body (a CDX answer without ``Content-Encoding``)."""
    kind = media_type(content_type) or ""
    extension = _EXTENSIONS.get(kind, ".bin")
    if body.startswith(b"\x1f\x8b"):
        return (".json" if kind in ("application/json", "text/plain") else extension) + ".gz"
    if extension == ".txt" and body.lstrip()[:1] in (b"[", b"{"):
        try:
            json.loads(body)
        except ValueError:
            return extension
        return ".json"
    return extension


def gunzip_bounded(body: bytes, limit: int) -> bytes:
    """The decompressed content of a gzip body (every member), at most ``limit + 1`` bytes
    of it, which is enough to tell that it exceeds ``limit``. Raises ``ValueError`` for a
    corrupt or truncated body."""
    output = b""
    data = body
    while data:
        decompressor = zlib.decompressobj(wbits=31)
        try:
            output += decompressor.decompress(data, limit + 1 - len(output))
        except zlib.error as exc:
            raise ValueError("the gzip body cannot be decompressed") from exc
        if len(output) > limit:
            return output
        if not decompressor.eof:
            raise ValueError("the gzip body is truncated")
        data = decompressor.unused_data
    return output


def refusal(body: bytes, contact_email: str | None) -> str | None:
    """Why a body cannot be written whole, or None. A gzip body is checked decompressed:
    its compressed bytes would hide every match."""
    if body.startswith(GZIP_MAGIC):
        try:
            body = gunzip_bounded(body, MAX_FIXTURE_BYTES)
        except ValueError as exc:
            return str(exc)
        if len(body) > MAX_FIXTURE_BYTES:
            return "the decompressed body has more than 1 MiB"
    if len(body) > MAX_FIXTURE_BYTES:
        return f"the body has {len(body)} bytes, more than 1 MiB"
    lowered = body.lower()
    if contact_email and contact_email.strip().lower().encode() in lowered:
        return "the body contains the contact address"
    if PRODUCT_TOKEN.lower().encode() in lowered:
        return "the body contains the User-Agent product token"
    if _BOT_TOKEN in body:
        return "the body contains a bot-manager token"
    if _EMAIL_RE.search(body):
        return "the body contains an e-mail address"
    return None


def capture_fixtures(
    config: CollectorConfig,
    settings: Settings,
    out_dir: Path,
    *,
    only: Sequence[str] = (),
    force: bool = False,
    transport: httpx2.BaseTransport | None = None,
    clock: Clock | None = None,
) -> list[CaptureResult]:
    """Capture the collector's fixture list into ``out_dir``. The caller has checked
    ``CONTACT_EMAIL``; unknown names in ``only`` raise ``ValueError``."""
    known = {fixture.name for fixture in config.fixtures}
    unknown = sorted(set(only) - known)
    if unknown:
        raise ValueError(f"{config.name} has no fixtures named {', '.join(unknown)}")
    selected = [fixture for fixture in config.fixtures if not only or fixture.name in only]
    sink = MemorySink()
    client = PoliteHttpClient(
        config,
        sink,
        user_agent=user_agent(settings.contact_email, settings.project_url),
        transport=transport,
        source_id=config.name,
        clock=clock,
        listing_host=None,
    )
    results: list[CaptureResult] = []
    with client:
        for fixture in selected:
            existing = sorted(out_dir.glob(f"{fixture.name}.*"))
            if existing and not force:
                results.append(CaptureResult(fixture.name, "kept", "exists (use --force)"))
                continue
            result = client.get(fixture.url)
            snapshot = result.snapshot
            if snapshot is None or result.outcome not in ("ok", "http_error"):
                detail = f"{result.outcome}: {result.error or result.status}"
                results.append(CaptureResult(fixture.name, "failed", detail))
                continue
            problem = refusal(snapshot.body, settings.contact_email)
            if problem is not None:
                detail = f"{problem}; capture an excerpt by hand"
                results.append(CaptureResult(fixture.name, "refused", detail))
                continue
            content_type = snapshot.headers.get("content-type")
            body_name = fixture.name + extension_for(content_type, snapshot.body)
            sha256 = hashlib.sha256(snapshot.body).hexdigest()
            retrieved = snapshot.fetched_at
            meta = {
                "fixture": fixture.name,
                "body": body_name,
                "collector": config.name,
                "source": config.source,
                "purpose": fixture.purpose,
                "url": result.url,
                "final_url": result.final_url,
                "redirects": list(result.redirects),
                "status": result.status,
                "retrieved_at": retrieved,
                "content_type": content_type,
                "headers": kept_headers(snapshot.headers),
                "sha256_original": sha256,
                "bytes_original": len(snapshot.body),
                "sha256_stored": sha256,
                "bytes_stored": len(snapshot.body),
                "trimmed": False,
                "trim_note": "original bytes, unchanged",
                "licence": config.licence.statement or config.licence.code,
                "attribution": f"{config.label}, retrieved {retrieved[:10]}; unchanged",
                "capture": f"mdt fixtures capture {config.name} (app {__version__}), {utc_now()}",
            }
            out_dir.mkdir(parents=True, exist_ok=True)
            for old in existing:
                old.unlink()
            body_path = out_dir / body_name
            body_path.write_bytes(snapshot.body)
            meta_text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
            (out_dir / f"{fixture.name}.meta.json").write_text(meta_text, encoding="utf-8")
            detail = f"HTTP {result.status}, {len(snapshot.body)} bytes"
            results.append(CaptureResult(fixture.name, "written", detail, body_path))
    return results
