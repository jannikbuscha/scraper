"""Tabular imports (docs/API.md §7.9): preview, dry run, run and the import history.

* ``POST /api/imports/preview``: sheets, columns, the first rows, a suggested mapping, the
  importable and key fields; writes nothing;
* ``POST /api/imports/dry-run`` → ``{"plan"}``; writes nothing;
* ``POST /api/imports`` → ``201 {"import", "result"}``; runs synchronously in the request;
* ``GET /api/imports`` (newest first) and ``GET /api/imports/{id}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import Field

from mdt.api.deps import SessionDep, SettingsDep
from mdt.api.listparams import ListParams
from mdt.api.schemas import Body
from mdt.importers.tabular import (
    ImportRequest,
    dry_run_import,
    get_import,
    list_imports,
    preview_import,
    run_import,
)


class PreviewBody(Body):
    """``POST /api/imports/preview``."""

    upload_id: str
    entity_type: str
    sheet: str | None = None


class DryRunBody(PreviewBody):
    """``POST /api/imports/dry-run``."""

    mapping: dict[str, str] = Field(default_factory=dict)
    key_field: str | None = None

    def request(self, note: str | None = None) -> ImportRequest:
        """The domain request."""
        return ImportRequest(
            upload_id=self.upload_id,
            entity_type=self.entity_type,
            sheet=self.sheet,
            mapping=self.mapping,
            key_field=self.key_field,
            note=note,
        )


class RunBody(DryRunBody):
    """``POST /api/imports``."""

    note: str | None = None


def post_preview(body: PreviewBody, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``POST /api/imports/preview``: writes nothing."""
    return preview_import(session, settings, body.upload_id, body.entity_type, body.sheet)


def post_dry_run(body: DryRunBody, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``POST /api/imports/dry-run`` → ``{"plan"}``: writes nothing."""
    return {"plan": dry_run_import(session, settings, body.request()).as_api()}


def post_import(body: RunBody, session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``POST /api/imports`` → ``201 {"import", "result"}``."""
    result = run_import(session, settings, body.request(body.note))
    return {"import": result.import_run, "result": result.plan.as_api()}


def get_imports(request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/imports``: newest first."""
    params = ListParams(request.query_params)
    items, total = list_imports(session, offset=params.offset, limit=params.page_size)
    return params.page_payload(items, total)


def get_one_import(import_id: str, session: SessionDep) -> dict[str, Any]:
    """``GET /api/imports/{id}``."""
    return {"import": get_import(session, import_id)}


def register(app: FastAPI) -> None:
    """Add the import routes."""
    app.add_api_route("/api/imports/preview", post_preview, methods=["POST"])
    app.add_api_route("/api/imports/dry-run", post_dry_run, methods=["POST"])
    app.add_api_route("/api/imports", post_import, methods=["POST"], status_code=201)
    app.add_api_route("/api/imports", get_imports, methods=["GET"])
    app.add_api_route("/api/imports/{import_id}", get_one_import, methods=["GET"])
