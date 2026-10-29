"""Export downloads (docs/API.md §5): CSV streams; XLSX is written in write-only mode to
an anonymous temporary file, which disappears when the download ends."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from typing import IO, Final

from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.datastructures import QueryParams
from starlette.responses import Response, StreamingResponse

from mdt.domain.export import ExportJob, start_export

CHUNK_BYTES: Final = 64 * 1024


def _download_headers(job: ExportJob) -> dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{job.filename}"',
        "Cache-Control": "no-store",
    }


def _file_chunks(handle: IO[bytes]) -> Iterator[bytes]:
    """The file's bytes in chunks; the file is closed (and so removed) at the end."""
    try:
        while chunk := handle.read(CHUNK_BYTES):
            yield chunk
    finally:
        handle.close()


def _xlsx_response(job: ExportJob, headers: dict[str, str]) -> Response:
    # The open file outlives this function: the response streams it and closes it.
    handle = tempfile.TemporaryFile(prefix="mdt-export-", suffix=".xlsx")  # noqa: SIM115
    try:
        job.write_xlsx(handle)
        size = handle.seek(0, 2)
        handle.seek(0)
    except BaseException:
        handle.close()
        raise
    return StreamingResponse(
        _file_chunks(handle),
        media_type=job.media_type,
        headers={**headers, "Content-Length": str(size)},
        background=BackgroundTask(handle.close),
    )


def export_response(session: Session, entity_type: str, params: QueryParams) -> Response:
    """Start the export (``429 busy`` while another runs, ``400 export_too_large`` over the
    row limit) and return the download. The export slot is released when the file is
    complete or the download ends."""
    job = start_export(session, entity_type, params)
    headers = _download_headers(job)
    try:
        if job.format == "xlsx":
            return _xlsx_response(job, headers)
        return StreamingResponse(
            job.iter_csv(),
            media_type=job.media_type,
            headers=headers,
            background=BackgroundTask(job.close),
        )
    except BaseException:
        job.close()
        raise
