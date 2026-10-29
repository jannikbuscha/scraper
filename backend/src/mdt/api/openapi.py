"""The OpenAPI document at ``/api/openapi.json`` (docs/API.md §6), aligned with the error
contract of API §1.2.

FastAPI generates the document from the route signatures. Left alone, it would promise
``422`` with FastAPI's ``HTTPValidationError`` body on every operation that has a body or
typed parameters, while the API answers ``400`` with the error envelope (the request
validation handler maps every validation error), and it would describe none of the other
error statuses or the required headers. :func:`contract_openapi` rewrites the generated
document accordingly. ``docs/API.md`` stays authoritative: the query parameters of the
list, facet, export, lookup and feed endpoints (API §4) are read from the raw query string
and are described there, not here.
"""

from __future__ import annotations

import copy
from typing import Any, Final

ENVELOPE_SCHEMA_NAME: Final = "ErrorEnvelope"
_ENVELOPE_REF: Final = {"$ref": f"#/components/schemas/{ENVELOPE_SCHEMA_NAME}"}
_ENVELOPE_SCHEMA: Final = {
    "title": ENVELOPE_SCHEMA_NAME,
    "description": "Every error response (docs/API.md §1.2).",
    "type": "object",
    "required": ["error"],
    "additionalProperties": False,
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message", "details"],
            "additionalProperties": False,
            "properties": {
                "code": {"type": "string", "examples": ["validation_error"]},
                "message": {"type": "string"},
                "details": {
                    "description": (
                        "Depends on the code: {field_path: [messages]} for "
                        "validation_error, the conflict payload for conflict, null for "
                        "most others."
                    )
                },
            },
        }
    },
}
#: FastAPI's own validation schemas, replaced by the envelope.
_FASTAPI_VALIDATION_SCHEMAS: Final = ("HTTPValidationError", "ValidationError")

_COMMON_ERRORS: Final = {
    "400": (
        "Invalid input: validation_error ({field_path: [messages]}; never 422), bad_filter, "
        "bad_sort, invalid_host and, for writes, author_required or author_invalid"
    ),
    "403": "cross_origin_forbidden: the X-Requested-With or Sec-Fetch-Site check failed",
    "500": "internal_error: an unexpected error ({request_id})",
    "503": "database_busy: the database is locked by another writer; retry after Retry-After",
}
_HEALTH_ERRORS: Final = ("400", "500")
_NOT_FOUND: Final = "not_found: an unknown entity type, record, version or revision"
_WRITE_ERRORS: Final = {
    "409": (
        "conflict, entity_deleted, invalid_state, has_dependents, unique_violation, "
        "reference_deleted, not_deletable or fixed_code"
    ),
    "413": "payload_too_large: the body is larger than 1 MiB",
    "415": "unsupported_media_type: the Content-Type is not application/json",
}
_EXPORT_ERRORS: Final = {"429": "busy: another export is running"}

_REQUESTED_WITH: Final = {
    "name": "X-Requested-With",
    "in": "header",
    "required": True,
    "description": "Must be `mdt` (docs/API.md §1.1); a cross-origin page cannot send it.",
    "schema": {"type": "string", "enum": ["mdt"]},
}
_AUTHOR: Final = {
    "name": "X-Author",
    "in": "header",
    "required": True,
    "description": (
        "The author's name, percent-encoded UTF-8 (encodeURIComponent); attribution, not "
        "authentication (docs/API.md §1.1, DATA_MODEL §7)."
    ),
    "schema": {"type": "string", "minLength": 1},
}
_READ_METHODS: Final = frozenset({"get", "head", "options"})
_HTTP_METHODS: Final = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})
HEALTH_PATH: Final = "/api/health"
DESCRIPTION: Final = (
    "Generated from the route signatures and aligned with the error envelope. "
    "docs/API.md is authoritative; the query parameters of the list, facet, export, "
    "lookup and feed endpoints (docs/API.md §4) are not listed here."
)


def _error_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": dict(_ENVELOPE_REF)}},
    }


def _operation_errors(path: str, method: str) -> dict[str, str]:
    if path == HEALTH_PATH:
        return {status: _COMMON_ERRORS[status] for status in _HEALTH_ERRORS}
    errors = dict(_COMMON_ERRORS)
    if "{" in path:
        errors["404"] = _NOT_FOUND
    if method not in _READ_METHODS:
        errors.update(_WRITE_ERRORS)
    if path.endswith("/export"):
        errors.update(_EXPORT_ERRORS)
    return dict(sorted(errors.items()))


def _headers(path: str, method: str) -> list[dict[str, Any]]:
    headers = [] if path == HEALTH_PATH else [copy.deepcopy(_REQUESTED_WITH)]
    if method not in _READ_METHODS:
        headers.append(copy.deepcopy(_AUTHOR))
    return headers


def contract_openapi(generated: dict[str, Any]) -> dict[str, Any]:
    """A copy of FastAPI's generated document with ``422`` replaced by ``400`` and the
    error envelope, the common error statuses per operation and the request headers of
    API §1.1."""
    schema = copy.deepcopy(generated)
    schema.setdefault("info", {})["description"] = DESCRIPTION
    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in _HTTP_METHODS:
                continue
            responses = operation.setdefault("responses", {})
            responses.pop("422", None)
            for status, description in _operation_errors(path, method).items():
                responses[status] = _error_response(description)
            known = {(p.get("in"), p.get("name")) for p in operation.get("parameters", [])}
            extra = [h for h in _headers(path, method) if ("header", h["name"]) not in known]
            if extra:
                operation["parameters"] = [*operation.get("parameters", []), *extra]
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    for name in _FASTAPI_VALIDATION_SCHEMAS:
        schemas.pop(name, None)
    schemas[ENVELOPE_SCHEMA_NAME] = copy.deepcopy(_ENVELOPE_SCHEMA)
    return schema
