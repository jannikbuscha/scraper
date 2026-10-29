"""Custom column types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from mdt.domain.clock import format_timestamp, is_timestamp


class UtcTimestamp(TypeDecorator[str]):
    """TEXT column holding ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (docs/DATA_MODEL.md §1.1).

    Accepts only aware UTC datetimes or strings in exactly that format; anything else
    raises ``ValueError`` before reaching the database. Values are read back as strings.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return format_timestamp(value)
        if isinstance(value, str) and is_timestamp(value):
            return value
        raise ValueError("UtcTimestamp accepts aware UTC datetimes or the storage format only")

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return value if value is None else str(value)


#: JSON for NOT NULL columns (lists and objects); never stores JSON ``null``.
JsonValue = JSON
#: JSON for nullable columns: Python ``None`` is stored as SQL NULL.
NullableJson = JSON(none_as_null=True)
