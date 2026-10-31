"""Raw snapshots (docs/API.md §7.3): metadata and the stored body.

The body is always sent as a download (``Content-Disposition: attachment``), so a stored
HTML page is never rendered in the app; snapshots never change, so it may be cached.
"""

from __future__ import annotations

import mimetypes
import re
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI
from starlette.responses import StreamingResponse

from mdt.api.deps import SessionDep, SettingsDep
from mdt.collectors.store import OCTET_STREAM, SnapshotStore
from mdt.domain.errors import NotFoundError

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def get_snapshot(snapshot_id: str, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/snapshots/{id}``."""
    record = SnapshotStore(settings.raw_path).record(session, snapshot_id)
    if record is None:
        raise NotFoundError()
    return {"snapshot": record.as_api()}


def content_disposition(filename: str) -> str:
    """``attachment`` with an ASCII fallback name and the UTF-8 name (RFC 6266)."""
    fallback = _UNSAFE_FILENAME.sub("_", filename) or "snapshot"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def get_snapshot_body(
    snapshot_id: str, session: SessionDep, settings: SettingsDep
) -> StreamingResponse:
    """``GET /api/snapshots/{id}/body``: the decompressed body as a download."""
    store = SnapshotStore(settings.raw_path)
    record = store.record(session, snapshot_id)
    if record is None:
        raise NotFoundError()
    path = store.path_of(record.sha256)
    if not path.is_file():
        raise NotFoundError("The stored body of this snapshot is missing")
    content_type = record.content_type or OCTET_STREAM
    filename = record.filename
    if not filename:
        extension = mimetypes.guess_extension(content_type) or ".bin"
        filename = f"{record.id}{extension}"
    return StreamingResponse(
        store.iter_body(record.sha256),
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition(filename),
            "Content-Length": str(record.size),
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


def register(app: FastAPI) -> None:
    """Add the snapshot routes."""
    app.add_api_route("/api/snapshots/{snapshot_id}", get_snapshot, methods=["GET"])
    app.add_api_route("/api/snapshots/{snapshot_id}/body", get_snapshot_body, methods=["GET"])
