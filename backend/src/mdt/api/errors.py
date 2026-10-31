"""The error envelope (docs/API.md §1.2) and the exception handlers that produce it.

Every error response is ``{"error": {"code", "message", "details"}}``. Unexpected errors
are logged with a request ID, and the response carries only that ID.
"""

from __future__ import annotations

import http.client
import logging
import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException
from starlette.routing import Match

from mdt.domain.errors import (
    DomainError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    ValidationError,
)
from mdt.domain.writes import unique_from_integrity

log = logging.getLogger("mdt.api")

#: Request locations that FastAPI puts first in a validation error's ``loc``.
_LOCATIONS: Final = frozenset({"body", "query", "path", "header", "cookie"})


def envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """The error envelope."""
    return {"error": {"code": code, "message": message, "details": details}}


def error_response(error: DomainError, headers: Mapping[str, str] | None = None) -> JSONResponse:
    """The JSON response for a domain error (its status and envelope)."""
    return JSONResponse(
        envelope(error.code, error.message, error.details),
        status_code=error.status,
        headers=dict(headers) if headers else None,
    )


def internal_error_response(request: Request, exc: BaseException) -> JSONResponse:
    """Log an unexpected error with a new request ID and answer ``500 internal_error``."""
    request_id = secrets.token_hex(8)
    log.error(
        "unhandled error (request_id=%s) on %s %s",
        request_id,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return error_response(InternalError(request_id))


# --------------------------------------------------------------------------------------
# Validation errors
# --------------------------------------------------------------------------------------


def error_path(loc: Sequence[Any]) -> str:
    """A field path such as ``items[0].id`` from a Pydantic/FastAPI error location."""
    parts = list(loc)
    source = "body"
    if parts and parts[0] in _LOCATIONS:
        source = str(parts.pop(0))
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path = f"{path}.{part}" if path else str(part)
    return path or source


def validation_details(errors: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """``{field_path: [messages]}`` from FastAPI validation errors."""
    details: dict[str, list[str]] = {}
    for error in errors:
        loc = error.get("loc") or ()
        # A JSON decode error locates the character offset, not a field.
        path = "body" if error.get("type") == "json_invalid" else error_path(loc)
        message = str(error.get("msg") or "Invalid value")
        messages = details.setdefault(path, [])
        if message not in messages:
            messages.append(message)
    return details


# --------------------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------------------


def _http_error(status: int) -> DomainError | None:
    """The domain error for an HTTP status raised by the framework, if it has one."""
    if status == 400:
        return ValidationError.single("body", "The request body could not be parsed")
    if status in (401, 403, 404):
        # 401/403 come from static files that cannot be read: they are reported as missing.
        return NotFoundError()
    if status == 405:
        return MethodNotAllowedError()
    return None


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A :class:`DomainError` from a handler or domain function → its envelope. A 500 is
    logged and answered as ``internal_error`` with a request ID; other 5xx errors (``502
    fetch_failed``, docs/API.md §7.8) are expected answers and keep their envelope."""
    assert isinstance(exc, DomainError)
    if exc.status == 500:
        return internal_error_response(request, exc)
    return error_response(exc)


def allowed_methods(request: Request) -> list[str]:
    """Every method that the API routes for the request's path accept. (Routing names only
    the first route that matched the path in its 405.)"""
    methods: set[str] = set()
    for route in request.app.router.routes:
        if isinstance(route, APIRoute) and route.matches(request.scope)[0] is not Match.NONE:
            methods |= route.methods or set()
    return sorted(methods)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Framework HTTP errors (unknown path, wrong method, unreadable body, …)."""
    assert isinstance(exc, HTTPException)
    status = exc.status_code
    if status >= 500:
        return internal_error_response(request, exc)
    error = _http_error(status)
    if error is None:
        phrase = http.client.responses.get(status, "Error")
        return JSONResponse(envelope("http_error", phrase), status_code=status)
    headers = None
    if status == 405:
        allow = ", ".join(allowed_methods(request)) or (exc.headers or {}).get("Allow")
        headers = {"Allow": allow} if allow else None
    return error_response(error, headers)


async def request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """Invalid path, query or body values → ``400 validation_error`` (never 422)."""
    assert isinstance(exc, RequestValidationError)
    return error_response(ValidationError(validation_details(exc.errors())))


async def integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A database constraint failure that the domain checks did not catch first: a UNIQUE
    violation is ``409 unique_violation``; anything else is an internal error."""
    assert isinstance(exc, IntegrityError)
    mapped = unique_from_integrity(exc)
    if mapped is not None:
        return error_response(mapped)
    return internal_error_response(request, exc)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Any other exception → ``500 internal_error`` with a request ID (details logged)."""
    return internal_error_response(request, exc)


def install_error_handlers(app: FastAPI) -> None:
    """Register the handlers that turn every error into the envelope."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
