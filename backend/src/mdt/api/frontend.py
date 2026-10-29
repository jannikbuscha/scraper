"""The built frontend (docs/API.md §6).

* ``/assets/*``: Starlette ``StaticFiles`` on ``FRONTEND_DIST/assets`` (symlinks are
  resolved and must stay inside), with ``Cache-Control: public, max-age=31536000,
  immutable``; a missing asset is 404, never ``index.html``.
* Root files: the regular files directly in ``FRONTEND_DIST`` (no symlinks, no
  subdirectories) are read once at startup and served by exact name.
* SPA fallback: every other GET/HEAD outside ``/api/`` returns the bytes of
  ``index.html`` with ``Cache-Control: no-cache``. The request path is never joined to a
  filesystem path.
* Other methods on non-API paths are 405; unknown ``/api`` paths are 404.
* Without ``index.html`` the API still works and non-API paths answer 503 with a hint.

:class:`FrontendApp` is installed as the router's default app, so it only sees requests
that no API route or mount matched (a known path with a wrong method stays a 405 there).
"""

from __future__ import annotations

import logging
import mimetypes
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from fastapi import FastAPI
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import PathLike, StaticFiles
from starlette.types import Receive, Scope, Send

from mdt.api.errors import envelope, error_response
from mdt.api.guard import is_api_path
from mdt.domain.errors import MethodNotAllowedError, NotFoundError

log = logging.getLogger("mdt.api")

INDEX_FILE: Final = "index.html"
ASSETS_PATH: Final = "/assets"
ASSET_CACHE_CONTROL: Final = "public, max-age=31536000, immutable"
NO_CACHE: Final = "no-cache"
READ_METHODS: Final = ("GET", "HEAD")
NOT_BUILT_CODE: Final = "frontend_not_built"
NOT_BUILT_MESSAGE: Final = (
    "The frontend is not built: run `make build` (or `cd frontend && npm run build`) and "
    "restart the server. The API under /api works without it."
)


@dataclass(frozen=True)
class RootFile:
    """A file served from the root of the build."""

    content: bytes
    media_type: str


@dataclass(frozen=True)
class FrontendBuild:
    """What was found in ``FRONTEND_DIST`` at startup."""

    root_files: Mapping[str, RootFile] = field(default_factory=dict)
    assets_dir: Path | None = None

    @property
    def index(self) -> RootFile | None:
        """``index.html``, or None without a build."""
        return self.root_files.get(INDEX_FILE)


def _media_type(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name, strict=False)
    return guessed or "application/octet-stream"


def load_build(dist: Path) -> FrontendBuild:
    """List the root files (regular files only, read into memory) and the assets
    directory of a build; a missing directory or ``index.html`` means "no build"."""
    if not dist.is_dir():
        return FrontendBuild()
    root_files: dict[str, RootFile] = {}
    assets_dir: Path | None = None
    with os.scandir(dist) as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False):
                root_files[entry.name] = RootFile(
                    Path(entry.path).read_bytes(), _media_type(entry.name)
                )
            elif entry.name == ASSETS_PATH.lstrip("/") and entry.is_dir(follow_symlinks=False):
                assets_dir = Path(entry.path)
    if INDEX_FILE not in root_files:
        return FrontendBuild()
    return FrontendBuild(root_files, assets_dir)


class ImmutableAssets(StaticFiles):
    """``StaticFiles`` for content-hashed assets: cacheable for a year."""

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = ASSET_CACHE_CONTROL
        return response


class FrontendApp:
    """Answers every request that no route matched (see the module docstring)."""

    def __init__(self, build: FrontendBuild) -> None:
        self.build = build

    def response_for(self, method: str, path: str) -> Response:
        """The response for a request that no API route or mount handled."""
        if is_api_path(path):
            return error_response(NotFoundError())
        if method not in READ_METHODS:
            return error_response(MethodNotAllowedError(), {"Allow": ", ".join(READ_METHODS)})
        index = self.build.index
        if index is None:
            return JSONResponse(envelope(NOT_BUILT_CODE, NOT_BUILT_MESSAGE), status_code=503)
        if path == ASSETS_PATH or path.startswith(ASSETS_PATH + "/"):
            return error_response(NotFoundError())
        name = path.removeprefix("/")
        served = self.build.root_files.get(name) if "/" not in name else None
        page = served or index
        return Response(
            page.content, media_type=page.media_type, headers={"Cache-Control": NO_CACHE}
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = self.response_for(scope["method"], scope["path"])
        await response(scope, receive, send)


def install(app: FastAPI, dist: Path) -> FrontendBuild:
    """Mount the assets and install the SPA fallback; call after the API routes."""
    build = load_build(dist)
    if build.index is None:
        log.warning("no frontend build found; non-API paths answer 503")
    elif build.assets_dir is not None:
        app.mount(ASSETS_PATH, ImmutableAssets(directory=build.assets_dir, follow_symlink=False))
    app.router.default = FrontendApp(build)
    return build
