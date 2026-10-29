"""The built frontend (docs/API.md §6).

* ``/assets/*``: Starlette ``StaticFiles`` on ``FRONTEND_DIST/assets``.
* Root files: the files directly in ``FRONTEND_DIST`` (e.g. ``favicon.svg``), by name.
* SPA fallback: every other GET/HEAD outside ``/api/`` returns ``index.html`` with
  ``Cache-Control: no-cache``, so a new build is picked up on the next page load.
* Other methods on non-API paths are 405; unknown ``/api`` paths are 404.
* Without ``index.html`` the API still works and non-API paths answer 503 with a hint.

:class:`FrontendApp` is installed as the router's default app, so it only sees requests
that no API route or mount matched (a known path with a wrong method stays a 405 there).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from fastapi import FastAPI
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from mdt.api.errors import envelope, error_response
from mdt.domain.errors import MethodNotAllowedError, NotFoundError

log = logging.getLogger("mdt.api")

INDEX_FILE: Final = "index.html"
ASSETS_PATH: Final = "/assets"
NO_CACHE: Final = "no-cache"
READ_METHODS: Final = ("GET", "HEAD")
NOT_BUILT_CODE: Final = "frontend_not_built"
NOT_BUILT_MESSAGE: Final = (
    "The frontend is not built: run `make build` (or `cd frontend && npm run build`) and "
    "restart the server. The API under /api works without it."
)


def is_api_path(path: str) -> bool:
    """True for ``/api`` and everything below it."""
    return path == "/api" or path.startswith("/api/")


class FrontendApp:
    """Answers every request that no route matched (see the module docstring)."""

    def __init__(self, dist: Path) -> None:
        self.dist = dist
        #: Names of the files at the root of the build, read once at startup.
        self.root_files = (
            {entry.name for entry in dist.iterdir() if entry.is_file()} if dist.is_dir() else set()
        )

    def response_for(self, method: str, path: str) -> Response:
        """The response for a request that no API route or mount handled."""
        if is_api_path(path):
            return error_response(NotFoundError())
        if method not in READ_METHODS:
            return error_response(MethodNotAllowedError(), {"Allow": ", ".join(READ_METHODS)})
        if INDEX_FILE not in self.root_files:
            return JSONResponse(envelope(NOT_BUILT_CODE, NOT_BUILT_MESSAGE), status_code=503)
        if path == ASSETS_PATH or path.startswith(ASSETS_PATH + "/"):
            return error_response(NotFoundError())
        name = path.removeprefix("/")
        served = name if name in self.root_files else INDEX_FILE
        return FileResponse(self.dist / served, headers={"Cache-Control": NO_CACHE})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = self.response_for(scope["method"], scope["path"])
        await response(scope, receive, send)


def install(app: FastAPI, dist: Path) -> None:
    """Mount the assets and install the SPA fallback; call after the API routes."""
    frontend = FrontendApp(dist)
    if INDEX_FILE not in frontend.root_files:
        log.warning("no frontend build found; non-API paths answer 503")
    elif (dist / "assets").is_dir():
        app.mount(ASSETS_PATH, StaticFiles(directory=dist / "assets"))
    app.router.default = frontend
