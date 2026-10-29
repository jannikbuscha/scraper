"""Typed domain errors map 1:1 to the error codes of docs/API.md §1.2."""

from __future__ import annotations

import pytest

from mdt.domain import errors
from mdt.domain.errors import (
    ConflictError,
    DomainError,
    EntityDeletedError,
    HasDependentsError,
    InternalError,
    InvalidStateError,
    Problems,
    ReferenceDeletedError,
    UniqueViolationError,
    ValidationError,
)

API_CODES = {
    "validation_error": 400,
    "author_required": 400,
    "author_invalid": 400,
    "invalid_host": 400,
    "bad_filter": 400,
    "bad_sort": 400,
    "evidence_required": 400,
    "export_too_large": 400,
    "cross_origin_forbidden": 403,
    "not_found": 404,
    "method_not_allowed": 405,
    "conflict": 409,
    "entity_deleted": 409,
    "invalid_state": 409,
    "has_dependents": 409,
    "unique_violation": 409,
    "reference_deleted": 409,
    "not_deletable": 409,
    "fixed_code": 409,
    "payload_too_large": 413,
    "uri_too_long": 414,
    "unsupported_media_type": 415,
    "busy": 429,
    "internal_error": 500,
    "database_busy": 503,
}


def _error_classes() -> list[type[DomainError]]:
    return [
        value
        for value in vars(errors).values()
        if isinstance(value, type) and issubclass(value, DomainError) and value is not DomainError
    ]


def test_every_api_code_has_exactly_one_error_class() -> None:
    codes: dict[str, list[str]] = {}
    for cls in _error_classes():
        codes.setdefault(cls.code, []).append(cls.__name__)
        if cls.code in API_CODES:
            assert cls.status == API_CODES[cls.code], cls.__name__
    # LockedFieldError is internal: channel collector is never reachable over HTTP.
    assert set(codes) == set(API_CODES) | {"locked_field"}
    assert all(len(names) == 1 for names in codes.values()), codes


def test_error_payloads() -> None:
    assert ValidationError({"name_en": ["is required"]}).to_dict() == {
        "code": "validation_error",
        "message": "Invalid input",
        "details": {"name_en": ["is required"]},
    }
    assert EntityDeletedError("2026-01-01T00:00:00.000000Z", "Alice").details == {
        "deleted_at": "2026-01-01T00:00:00.000000Z",
        "deleted_by": "Alice",
    }
    assert InvalidStateError("deleted").details == {"state": "deleted"}
    assert HasDependentsError({"service": 12}).details == {"service": 12}
    assert UniqueViolationError("slug", None).details == {"field": "slug", "existing": None}
    assert ReferenceDeletedError("project_id", "prj_X", "project", "Label").details == {
        "field": "project_id",
        "id": "prj_X",
        "type": "project",
        "label": "Label",
    }
    assert InternalError("req-1").details == {"request_id": "req-1"}
    conflict = ConflictError({"action": "patch"})
    assert conflict.payload == {"action": "patch"} and conflict.status == 409


def test_problems_collects_and_raises_together() -> None:
    problems = Problems()
    assert not problems
    problems.add("a", "first")
    problems.add("a", "first")
    problems.add("b", "second")
    with pytest.raises(ValidationError) as caught:
        problems.raise_if_any()
    assert caught.value.details == {"a": ["first"], "b": ["second"]}
    Problems().raise_if_any()  # nothing recorded: no error
