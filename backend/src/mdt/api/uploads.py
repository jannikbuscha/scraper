"""Uploads (docs/API.md §7.7): the raw request body is stored as an upload snapshot.

``POST /api/uploads?filename=<name>`` takes the file as the request body (any content type,
no multipart) and answers ``201 {"upload": Snapshot, "suggested": Suggested}``. The body is
spooled while it arrives (in memory up to a few MiB, then in a temporary file), so a large
file never has to fit into memory; the snapshot store then streams it into
``DATA_DIR/raw``. There is no size limit (D-15).
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from typing import IO, Any

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from mdt.api.deps import AppContext, app_context
from mdt.collectors.store import base_name
from mdt.documents.manual import store_upload
from mdt.domain.errors import ValidationError

#: Bodies up to this size stay in memory while they are spooled.
SPOOL_IN_MEMORY = 8 * 1024 * 1024
_CHUNK = 1 << 16


def _chunks(spool: IO[bytes]) -> Iterator[bytes]:
    while chunk := spool.read(_CHUNK):
        yield chunk


def _store(context: AppContext, spool: IO[bytes], filename: str) -> dict[str, Any]:
    """Runs in a worker thread with a session of its own."""
    session = context.session_factory()
    try:
        record, suggested = store_upload(session, context.settings, _chunks(spool), filename)
    finally:
        session.close()
    return {"upload": record.as_api(), "suggested": suggested.as_api()}


async def post_upload(request: Request) -> dict[str, Any]:
    """``POST /api/uploads?filename=<name>`` → ``201 {upload, suggested}``. A missing or
    empty file name (path parts are dropped) or an empty body is ``400``."""
    filename = base_name(request.query_params.get("filename") or "")
    if not filename:
        raise ValidationError.single("filename", "is required (the file's name)")
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_IN_MEMORY) as spool:
        size = 0
        async for chunk in request.stream():
            if chunk:
                spool.write(chunk)
                size += len(chunk)
        if not size:
            raise ValidationError.single("body", "the uploaded file is empty")
        spool.seek(0)
        return await run_in_threadpool(_store, app_context(request), spool, filename)


def register(app: FastAPI) -> None:
    """Add the upload route."""
    app.add_api_route("/api/uploads", post_upload, methods=["POST"], status_code=201)
