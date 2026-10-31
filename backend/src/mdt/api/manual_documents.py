"""Manual documents (docs/API.md §7.8): fetch a URL into a snapshot, and create a document
from a snapshot.

* ``POST /api/documents/fetch {"url"}`` → ``201 {"snapshot", "suggested"}``: the URL is
  fetched with the polite client within 60 s (a Wayback capture URL as an archived copy);
* ``POST /api/documents/manual {"snapshot_id", …}`` → ``201 {"item", "revision_id",
  "warnings"}``: a document on channel ``ui`` from an upload or a fetched snapshot.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from mdt.api.deps import SessionDep, SettingsDep
from mdt.api.schemas import Body
from mdt.documents.manual import create_manual_document, fetch_document
from mdt.domain.serialize import get_item


class FetchBody(Body):
    """``POST /api/documents/fetch``."""

    url: str


class ManualDocumentBody(Body):
    """``POST /api/documents/manual``; the values are validated by the domain."""

    snapshot_id: str
    title: str | None = None
    url: str | None = None
    retrieved_at: str | None = None
    doc_type: str | None = None
    language: str | None = None
    publisher: str | None = None
    published: str | None = None
    published_basis: str | None = None
    published_text: str | None = None
    license: str | None = None
    note: str | None = None


def post_fetch(body: FetchBody, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``POST /api/documents/fetch`` → ``201 {snapshot, suggested}``; a failed fetch is
    ``502 fetch_failed {reason, status}`` (:class:`~mdt.collectors.errors.FetchFailedError`)."""
    record, suggested = fetch_document(session, settings, body.url)
    return {"snapshot": record.as_api(), "suggested": suggested.as_api()}


def post_manual_document(
    body: ManualDocumentBody, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """``POST /api/documents/manual`` → ``201 {item, revision_id, warnings}``."""
    values = body.model_dump(exclude_unset=True, exclude={"note"})
    created = create_manual_document(session, settings, values, note=body.note)
    return {
        "item": get_item(session, "document", created.result.entity_id),
        "revision_id": created.result.revision_id,
        "warnings": created.warnings_payload(),
    }


def register(app: FastAPI) -> None:
    """Add the manual document routes."""
    app.add_api_route(
        "/api/documents/fetch", post_fetch, methods=["POST"], status_code=201, response_model=None
    )
    app.add_api_route(
        "/api/documents/manual", post_manual_document, methods=["POST"], status_code=201
    )
