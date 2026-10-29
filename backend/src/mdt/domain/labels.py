"""Labels of entities (docs/API.md §2), computed in batches.

:func:`ref_infos` resolves any IDs (deleted ones included) to
``{id, type, label, deleted}``; nested labels (an event's subject, a participation's
organisation and subject, …) are fetched with one query per type and level.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.domain.dates import partial_date_from_columns
from mdt.domain.records import table_of
from mdt.domain.registry import ENTITY_TYPES, type_of_id
from mdt.domain.vocab import term_labels

_MAX_DEPTH = 6

#: Columns needed per label rule (besides id and deleted_at).
_RULE_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "names": ("name_en", "name_uk"),
    "event": ("event_type", "subject_id", "date_start", "date_end", "date_precision"),
    "title": ("title",),
    "participation": ("organization_id", "role", "subject_id"),
    "relation": ("from_id", "relation_type", "to_id"),
    "indicator": ("metric", "value", "unit"),
    "evidence": ("target", "subject_id"),
    "vocabulary_term": ("vocabulary", "code"),
    "name": ("name",),
    "comment": ("subject_id", "field"),
}
#: Vocabulary codes used in labels: (rule, column) → vocabulary.
_LABEL_VOCABULARIES: Mapping[tuple[str, str], str] = {
    ("event", "event_type"): "event_type",
    ("participation", "role"): "participation_role",
    ("relation", "relation_type"): "relation_type",
}
_NESTED: Mapping[str, tuple[str, ...]] = {
    "event": ("subject_id",),
    "participation": ("organization_id", "subject_id"),
    "relation": ("from_id", "to_id"),
    "evidence": ("subject_id",),
    "comment": ("subject_id",),
}


@dataclass(frozen=True)
class RefInfo:
    """Label information of one ID."""

    id: str
    type: str
    label: str
    deleted: bool

    def as_dict(self) -> dict[str, Any]:
        """``{id, type, label, deleted}``."""
        return {"id": self.id, "type": self.type, "label": self.label, "deleted": self.deleted}


def format_number(value: float | int | None) -> str:
    """Numbers in labels: integral floats without a decimal part."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value)


class _Labeler:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.rows: dict[str, tuple[str, dict[str, Any]]] = {}
        self.vocab_labels: dict[tuple[str, str], str] = {}
        self.labels: dict[str, str] = {}

    def fetch(self, ids: Iterable[str]) -> set[str]:
        by_type: dict[str, list[str]] = defaultdict(list)
        for entity_id in ids:
            entity_type = type_of_id(entity_id)
            if entity_type is not None and entity_id not in self.rows:
                by_type[entity_type].append(entity_id)
        fetched: set[str] = set()
        for entity_type, type_ids in by_type.items():
            spec = ENTITY_TYPES[entity_type]
            table = table_of(spec)
            columns = [table.c.id, table.c.deleted_at] + [
                table.c[name] for name in _RULE_COLUMNS[spec.label_rule]
            ]
            if spec.label_rule == "names" and "slug" in table.c:
                columns.append(table.c.slug)
            for chunk_start in range(0, len(type_ids), 500):
                chunk = type_ids[chunk_start : chunk_start + 500]
                for row in self.session.execute(select(*columns).where(table.c.id.in_(chunk))):
                    mapping = dict(row._mapping)
                    self.rows[mapping["id"]] = (entity_type, mapping)
                    fetched.add(mapping["id"])
        return fetched

    def resolve(self, ids: Iterable[str]) -> None:
        pending = set(ids)
        for _ in range(_MAX_DEPTH):
            fetched = self.fetch(pending)
            nested: set[str] = set()
            for entity_id in fetched:
                entity_type, row = self.rows[entity_id]
                for column in _NESTED.get(ENTITY_TYPES[entity_type].label_rule, ()):
                    if row.get(column):
                        nested.add(row[column])
            pending = {entity_id for entity_id in nested if entity_id not in self.rows}
            if not pending:
                break
        pairs = set()
        for entity_type, row in self.rows.values():
            rule = ENTITY_TYPES[entity_type].label_rule
            for (vocab_rule, column), vocabulary in _LABEL_VOCABULARIES.items():
                if vocab_rule == rule and row.get(column):
                    pairs.add((vocabulary, row[column]))
        self.vocab_labels = term_labels(self.session, pairs)

    def vocab(self, vocabulary: str, code: str | None) -> str:
        if code is None:
            return ""
        return self.vocab_labels.get((vocabulary, code), code)

    def label(self, entity_id: str | None, depth: int = 0) -> str:
        if entity_id is None:
            return ""
        if entity_id in self.labels:
            return self.labels[entity_id]
        if entity_id not in self.rows or depth > _MAX_DEPTH:
            return entity_id
        entity_type, row = self.rows[entity_id]
        label = self._compute(entity_type, row, depth)
        self.labels[entity_id] = label
        return label

    def _compute(self, entity_type: str, row: Mapping[str, Any], depth: int) -> str:
        spec = ENTITY_TYPES[entity_type]
        rule = spec.label_rule
        nested = depth + 1
        if rule == "names":
            return str(row.get("name_en") or row.get("name_uk") or row.get("slug") or row["id"])
        if rule == "event":
            date = partial_date_from_columns(
                row["date_start"], row["date_end"], row["date_precision"]
            )
            return " · ".join(
                (
                    self.vocab("event_type", row["event_type"]),
                    self.label(row["subject_id"], nested),
                    date or "undated",
                )
            )
        if rule == "title":
            return str(row.get("title") or row["id"])
        if rule == "participation":
            return " · ".join(
                (
                    self.label(row["organization_id"], nested),
                    self.vocab("participation_role", row["role"]),
                    self.label(row["subject_id"], nested),
                )
            )
        if rule == "relation":
            return " ".join(
                (
                    self.label(row["from_id"], nested),
                    self.vocab("relation_type", row["relation_type"]),
                    self.label(row["to_id"], nested),
                )
            )
        if rule == "indicator":
            unit = f" {row['unit']}" if row.get("unit") else ""
            return f"{row['metric']}: {format_number(row['value'])}{unit}"
        if rule == "evidence":
            return f"{row['target']} · {self.label(row['subject_id'], nested)}"
        if rule == "vocabulary_term":
            return f"{row['vocabulary']}:{row['code']}"
        if rule == "name":
            return str(row.get("name") or row["id"])
        return self._comment_label(row, nested)

    def _comment_label(self, row: Mapping[str, Any], depth: int) -> str:
        label = f"Comment on {self.label(row['subject_id'], depth)}"
        field = row.get("field")
        if field:
            subject_type = type_of_id(row["subject_id"])
            spec = ENTITY_TYPES.get(subject_type) if subject_type else None
            field_label = spec.field(field).label if spec and spec.has_field(field) else field
            label += f" · {field_label}"
        return label


def ref_infos(session: Session, ids: Iterable[str | None]) -> dict[str, RefInfo]:
    """Label information for every known ID in ``ids`` (unknown IDs are omitted)."""
    wanted = [entity_id for entity_id in dict.fromkeys(ids) if entity_id]
    labeler = _Labeler(session)
    labeler.resolve(wanted)
    result = {}
    for entity_id in wanted:
        if entity_id in labeler.rows:
            entity_type, row = labeler.rows[entity_id]
            result[entity_id] = RefInfo(
                id=entity_id,
                type=entity_type,
                label=labeler.label(entity_id),
                deleted=row["deleted_at"] is not None,
            )
    return result


def ref_info(session: Session, entity_id: str) -> RefInfo | None:
    """Label information of one ID, or None if it does not exist."""
    return ref_infos(session, [entity_id]).get(entity_id)


def entity_label(session: Session, entity_id: str) -> str:
    """The label of one entity (its ID if it does not exist)."""
    info = ref_info(session, entity_id)
    return info.label if info else entity_id


def refs_payload(session: Session, ids: Iterable[str | None]) -> dict[str, dict[str, Any]]:
    """``refs`` keyed by ID: ``{id: {id, type, label, deleted}}``."""
    return {entity_id: info.as_dict() for entity_id, info in ref_infos(session, ids).items()}
