"""Typed domain errors. Each class maps 1:1 to an error code of docs/API.md §1.2.

The HTTP layer turns a :class:`DomainError` into the envelope
``{"error": {"code", "message", "details"}}`` with :attr:`DomainError.status`.
Messages never contain submitted values, SQL or file paths.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar


class DomainError(Exception):
    """Base class of all errors with an API error code."""

    code: ClassVar[str] = "internal_error"
    status: ClassVar[int] = 500
    default_message: ClassVar[str] = "Internal error"

    def __init__(self, message: str | None = None, details: Mapping[str, Any] | None = None):
        self.message = message or self.default_message
        self.details: dict[str, Any] | None = dict(details) if details is not None else None
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Return the error object of the API envelope."""
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(DomainError):
    """400: invalid input. ``details`` maps field paths to lists of messages."""

    code = "validation_error"
    status = 400
    default_message = "Invalid input"

    def __init__(self, details: Mapping[str, Sequence[str]], message: str | None = None):
        super().__init__(message, {path: list(msgs) for path, msgs in details.items()})

    @classmethod
    def single(cls, path: str, message: str) -> ValidationError:
        """Build an error for one field path."""
        return cls({path: [message]})


class BadFilterError(DomainError):
    """400: a malformed or unknown list filter."""

    code = "bad_filter"
    status = 400
    default_message = "Invalid filter"


class BadSortError(DomainError):
    """400: a sort on an unknown or unsortable field."""

    code = "bad_sort"
    status = 400
    default_message = "Invalid sort"


class EvidenceRequiredError(DomainError):
    """400: field verification without matching evidence."""

    code = "evidence_required"
    status = 400
    default_message = "Verification requires an evidence record that targets this field"


class NotFoundError(DomainError):
    """404: an unknown entity type, record or version."""

    code = "not_found"
    status = 404
    default_message = "Not found"


class MethodNotAllowedError(DomainError):
    """405: a method that the path does not support."""

    code = "method_not_allowed"
    status = 405
    default_message = "Method not allowed"


class EntityDeletedError(DomainError):
    """409: a write to a soft-deleted record."""

    code = "entity_deleted"
    status = 409
    default_message = "The record is deleted"

    def __init__(self, deleted_at: str | None, deleted_by: str | None):
        super().__init__(details={"deleted_at": deleted_at, "deleted_by": deleted_by})


class InvalidStateError(DomainError):
    """409: an action that the record's state does not allow."""

    code = "invalid_state"
    status = 409
    default_message = "The action is not possible in the current state"

    def __init__(self, state: str, message: str | None = None):
        super().__init__(message, {"state": state})


class HasDependentsError(DomainError):
    """409: deleting a record with live dependents without cascade."""

    code = "has_dependents"
    status = 409
    default_message = "The record has dependent records"

    def __init__(self, counts: Mapping[str, int], message: str | None = None):
        super().__init__(message, details=dict(counts))


class UniqueViolationError(DomainError):
    """409: a value that another record already uses."""

    code = "unique_violation"
    status = 409
    default_message = "The value is already used by another record"

    def __init__(self, field: str, existing: Mapping[str, Any] | None):
        super().__init__(details={"field": field, "existing": existing})


class ReferenceDeletedError(DomainError):
    """409: setting a reference to a deleted record."""

    code = "reference_deleted"
    status = 409
    default_message = "The referenced record is deleted"

    def __init__(self, field: str, ref_id: str, ref_type: str, label: str | None):
        super().__init__(details={"field": field, "id": ref_id, "type": ref_type, "label": label})


class NotDeletableError(DomainError):
    """409: deleting a vocabulary term (deactivate it instead)."""

    code = "not_deletable"
    status = 409
    default_message = "Records of this type cannot be deleted; deactivate them instead"


class FixedCodeError(DomainError):
    """409: adding or deactivating a fixed vocabulary code."""

    code = "fixed_code"
    status = 409
    default_message = "Fixed codes cannot be added or deactivated"


class LockedFieldError(DomainError):
    """A collector tried to change fields that a person locked (internal; channel collector
    is never reachable over HTTP). The reconciler turns these into proposals."""

    code = "locked_field"
    status = 409
    default_message = "The fields are locked by a person"

    def __init__(self, fields: Sequence[str]):
        super().__init__(details={"fields": sorted(fields)})


class InternalError(DomainError):
    """500: an unexpected error; details carry the request ID only."""

    code = "internal_error"
    status = 500
    default_message = "Internal error"

    def __init__(self, request_id: str):
        super().__init__(details={"request_id": request_id})


class Problems:
    """Collects validation problems per field path and raises them together."""

    def __init__(self) -> None:
        self._items: dict[str, list[str]] = {}

    def add(self, path: str, message: str) -> None:
        """Record a problem for ``path`` (duplicates are ignored)."""
        messages = self._items.setdefault(path, [])
        if message not in messages:
            messages.append(message)

    def __bool__(self) -> bool:
        return bool(self._items)

    def raise_if_any(self) -> None:
        """Raise a :class:`ValidationError` with all recorded problems."""
        if self._items:
            raise ValidationError(self._items)
