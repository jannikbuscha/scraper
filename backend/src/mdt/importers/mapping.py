"""Mappings and cell values of an import (docs/COLLECTORS.md §9.3, docs/DATA_MODEL.md
§17.1).

* **Importable fields:** the editable stored fields of the type (create-only ones on
  create); never system, derived or virtual fields, never ``links``. ``id`` is a key only.
* **Suggested mapping:** a header that equals a field's name or label (case-insensitive,
  trimmed) maps to that field.
* **Key fields:** ``id``, plus ``slug`` (project, organization) or ``url`` (document).
* **Cells:** an empty cell means "not provided"; codes or English term labels for
  vocabularies; items separated by ``;`` for lists; ``true``/``false``, ``yes``/``no``,
  ``1``/``0`` for booleans; decimal numbers with ``.``; IDs, or slugs of projects and
  organisations, for references. Everything else is passed on as text and validated by the
  write path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.domain.errors import ValidationError
from mdt.domain.ids import ID_RE
from mdt.domain.normalize import ValueProblem
from mdt.domain.records import table_of
from mdt.domain.registry import ENTITY_TYPES, TABLE_TYPES, EntityTypeSpec, FieldSpec
from mdt.domain.vocab import TermIndex

LIST_SEPARATOR = ";"
#: The key column of a mapping: an ID, not a field.
ID_KEY = "id"
#: Key fields per type besides ``id``.
_KEY_FIELDS: Mapping[str, tuple[str, ...]] = {
    "project": ("slug",),
    "organization": ("slug",),
    "document": ("url",),
}
_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0"})
_INT = re.compile(r"^[+-]?\d+$")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def table_spec(entity_type: Any) -> EntityTypeSpec:
    """The registry entry of one of the five table types."""
    if entity_type not in TABLE_TYPES:
        raise ValidationError.single("entity_type", f"must be one of {', '.join(TABLE_TYPES)}")
    return ENTITY_TYPES[entity_type]


def is_importable(spec: FieldSpec) -> bool:
    """Editable stored fields (create-only ones on create); never system, derived or
    virtual fields, never ``links``."""
    return (
        spec.stored
        and spec.editable
        and not spec.system
        and not spec.system_column
        and not spec.internal
        and spec.type != "doc_links"
    )


def importable_fields(entity_type: str) -> list[str]:
    """The fields an import may write for the type, in registry order."""
    return [spec.name for spec in table_spec(entity_type).fields if is_importable(spec)]


def key_fields(entity_type: str) -> list[str]:
    """``id`` plus the type's natural key (``slug`` or ``url``)."""
    return [ID_KEY, *_KEY_FIELDS.get(entity_type, ())]


def suggest_mapping(entity_type: str, columns: Sequence[str]) -> dict[str, str]:
    """A header that equals a field's name or label (case-insensitive, trimmed) maps to
    that field; ``id`` to the ID key. The first such header wins."""
    spec = table_spec(entity_type)
    names: dict[str, str] = {ID_KEY: ID_KEY}
    for name in importable_fields(entity_type):
        names.setdefault(name.casefold(), name)
        names.setdefault(spec.field(name).label.strip().casefold(), name)
    mapping: dict[str, str] = {}
    for column in columns:
        target = names.get(column.strip().casefold())
        if target is not None and target not in mapping.values():
            mapping[column] = target
    return mapping


def check_mapping(
    entity_type: str, columns: Sequence[str], mapping: Any, key_field: Any
) -> dict[str, str]:
    """Validate a mapping ``{column: field}`` and the key field (400 with the paths
    ``mapping.<column>`` and ``key_field``)."""
    if not isinstance(mapping, Mapping):
        raise ValidationError.single("mapping", "must map columns to fields")
    allowed = {*importable_fields(entity_type), ID_KEY}
    problems: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    for column, target in mapping.items():
        path = f"mapping.{column}"
        if column not in columns:
            problems[path] = ["is not a column of the file"]
        elif not isinstance(target, str) or target not in allowed:
            problems[path] = ["is not an importable field of this type"]
        elif target in seen:
            problems[path] = [f"maps to {target}, which column {seen[target]} maps to already"]
        else:
            seen[target] = column
    if key_field is not None:
        if key_field not in key_fields(entity_type):
            problems["key_field"] = [f"must be one of {', '.join(key_fields(entity_type))}"]
        elif key_field not in seen:
            problems["key_field"] = [f"map a column to {key_field} to use it as the key"]
    if problems:
        raise ValidationError(problems)
    return {str(column): str(target) for column, target in mapping.items()}


# --------------------------------------------------------------------------------------
# Cell values (docs/COLLECTORS.md §9.3)
# --------------------------------------------------------------------------------------


class CellParser:
    """Turns cell texts into API values: codes or English term labels for vocabularies,
    ``;``-separated lists, booleans, numbers, and IDs or slugs for references."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.terms = TermIndex(session)
        self._labels: dict[str, dict[str, str]] = {}

    def parse(self, spec: FieldSpec, text: str) -> Any:
        """The API value of a non-empty cell (raises ValueProblem)."""
        value = text.strip()
        if spec.type in ("vocab_list", "string_list", "url_list", "alias_list"):
            items = [item.strip() for item in value.split(LIST_SEPARATOR) if item.strip()]
            if spec.type == "vocab_list":
                return [self.code(spec, item) for item in items]
            if spec.type == "alias_list":
                return [{"text": item} for item in items]
            return items
        if spec.type == "vocab":
            return self.code(spec, value)
        if spec.type == "bool":
            folded = value.casefold()
            if folded in _TRUE or folded in _FALSE:
                return folded in _TRUE
            raise ValueProblem("must be true or false (also yes/no, 1/0)")
        if spec.type == "int":
            if not _INT.fullmatch(value):
                raise ValueProblem("must be a whole number")
            return int(value)
        if spec.type == "number":
            if not _NUMBER.fullmatch(value):
                raise ValueProblem("must be a decimal number with '.'")
            return float(value)
        if spec.type == "ref":
            return self.reference(spec, value)
        return value

    def code(self, spec: FieldSpec, value: str) -> str:
        """A vocabulary code: the code itself, or a term's ``label_en`` (case-insensitive).
        Anything else is passed on, so validation reports the unknown code."""
        vocabulary = spec.vocabulary or ""
        terms = self.terms.terms(vocabulary)
        if value in terms:
            return value
        if vocabulary not in self._labels:
            labels: dict[str, str] = {}
            for code, term in sorted(terms.items()):
                labels.setdefault(code.casefold(), code)
                labels.setdefault(term.label_en.strip().casefold(), code)
            self._labels[vocabulary] = labels
        return self._labels[vocabulary].get(value.casefold(), value)

    def reference(self, spec: FieldSpec, value: str) -> str:
        """An ID of an allowed type, or the slug of a project or organisation."""
        if ID_RE.fullmatch(value):
            return value
        for ref_type in spec.ref_types or ():
            if ref_type in ("project", "organization"):
                table = table_of(ENTITY_TYPES[ref_type])
                found = self.session.execute(
                    select(table.c.id).where(table.c.slug == value)
                ).scalar()
                if found is not None:
                    return str(found)
        return value
