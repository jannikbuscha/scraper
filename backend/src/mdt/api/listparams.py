"""Query parameters of the Phase 2 list endpoints (docs/API.md §7.1): ``page`` and
``page_size`` as for tables, and plain filters, comma-separated where they accept several
values; unknown values of known parameters are ``400 validation_error``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from starlette.datastructures import QueryParams

from mdt.domain.errors import ValidationError
from mdt.domain.listquery import last_param, param_pairs, parse_paging, split_list


class ListParams:
    """The query parameters of one list request."""

    def __init__(self, params: QueryParams) -> None:
        self.pairs = param_pairs(params)
        self.page, self.page_size = parse_paging(self.pairs)

    def raw(self, name: str) -> str | None:
        """The last value of ``name`` (None if absent or blank)."""
        value = last_param(self.pairs, name)
        return value if value not in (None, "") else None

    def choices(self, name: str, allowed: Sequence[str]) -> list[str]:
        """A comma-separated list of allowed values (empty: no filter)."""
        values = split_list(self.raw(name))
        if any(value not in allowed for value in values):
            raise ValidationError.single(name, f"must be one of {', '.join(allowed)}")
        return values

    def flag(self, name: str) -> bool | None:
        """``true``/``false`` (None: no filter)."""
        value = self.raw(name)
        if value is None:
            return None
        if value not in ("true", "false"):
            raise ValidationError.single(name, "must be true or false")
        return value == "true"

    @property
    def offset(self) -> int:
        """Rows to skip for the page."""
        return (self.page - 1) * self.page_size

    def page_payload(self, items: list[Any], total: int) -> dict[str, Any]:
        """``{items, total, page, page_size}``."""
        return {"items": items, "total": total, "page": self.page, "page_size": self.page_size}
