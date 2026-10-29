"""The error envelope (docs/API.md §1.2) and the exception handlers that produce it.

Every error response is ``{"error": {"code", "message", "details"}}``. Messages never
contain submitted values, exception text, SQL, file paths or stack traces; unexpected
errors are logged with a request ID, and the response carries only that ID.
"""

from __future__ import annotations

import http.client
import logging
import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException
from starlette.routing import Match

from mdt.domain.errors import (
    DatabaseBusyError,
    DomainError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    UriTooLongError,
    ValidationError,
)
from mdt.domain.writes import unique_from_integrity

log = logging.getLogger("mdt.api")

#: Request locations that FastAPI puts first in a validation error's ``loc``.
_LOCATIONS: Final = frozenset({"body", "query", "path", "header", "cookie"})
MAX_PATH_CHARS: Final = 200


_SURROGATES: Final = re.compile(r"[\ud800-\udfff]")


def _encodable(value: Any) -> Any:
    """``value`` with unpaired surrogates in strings and keys replaced by U+FFFD, so the
    envelope can always be encoded as UTF-8 (a path may repeat a key the client sent)."""
    if isinstance(value, str):
        return _SURROGATES.sub("\ufffd", value)
    if isinstance(value, dict):
        return {_encodable(key): _encodable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_encodable(item) for item in value]
    return value


def envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """The error envelope."""
    return {"error": {"code": code, "message": _encodable(message), "details": _encodable(details)}}


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
    return (path or source)[:MAX_PATH_CHARS]


def validation_details(errors: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """``{field_path: [messages]}`` from FastAPI validation errors; the submitted input
    (``input``) and the error context are never copied."""
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
    known: dict[int, type[DomainError]] = {
        405: MethodNotAllowedError,
        413: PayloadTooLargeError,
        414: UriTooLongError,
        415: UnsupportedMediaTypeError,
    }
    error_class = known.get(status)
    return error_class() if error_class is not None else None


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A :class:`DomainError` from a handler or domain function → its envelope."""
    assert isinstance(exc, DomainError)
    if isinstance(exc, DatabaseBusyError):
        return busy_response(request)
    if exc.status >= 500:
        return internal_error_response(request, exc)
    return error_response(exc)


def busy_response(request: Request) -> JSONResponse:
    """``503 database_busy`` with ``Retry-After``: the request found the database locked
    (or no free connection) and changed nothing; repeating it later is safe."""
    log.warning("database busy on %s %s", request.method, request.url.path)
    return error_response(
        DatabaseBusyError(), {"Retry-After": str(DatabaseBusyError.retry_after_seconds)}
    )


#: SQLite result codes of a lock that did not clear within ``busy_timeout``.
_SQLITE_BUSY: Final = 5
_SQLITE_LOCKED: Final = 6
_BUSY_MESSAGES: Final = ("database is locked", "database table is locked", "database is busy")


def is_busy_error(exc: OperationalError) -> bool:
    """True if a database error means "locked by someone else, try again later"
    (``SQLITE_BUSY``/``SQLITE_LOCKED``, extended codes included)."""
    original = exc.orig
    code = getattr(original, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in (_SQLITE_BUSY, _SQLITE_LOCKED)
    return any(message in str(original).lower() for message in _BUSY_MESSAGES)


async def operational_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """A lock that did not clear within the busy timeout → ``503 database_busy`` (the
    write unit was rolled back); any other database failure is an internal error."""
    assert isinstance(exc, OperationalError)
    if is_busy_error(exc):
        return busy_response(request)
    return internal_error_response(request, exc)


async def pool_timeout_handler(request: Request, exc: Exception) -> JSONResponse:
    """No database connection became free in time → ``503 database_busy``."""
    return busy_response(request)


def allowed_methods(request: Request) -> list[str]:
    """Every method that the API routes for the request's path accept. (Routing names only
    the first route that matched the path in its 405.)"""
    methods: set[str] = set()
    for route in request.app.router.routes:
        if isinstance(route, APIRoute) and route.matches(request.scope)[0] is not Match.NONE:
            methods |= route.methods or set()
    return sorted(methods)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Framework HTTP errors (unknown path, wrong method, body too large, …)."""
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
    app.add_exception_handler(OperationalError, operational_error_handler)
    app.add_exception_handler(PoolTimeoutError, pool_timeout_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
