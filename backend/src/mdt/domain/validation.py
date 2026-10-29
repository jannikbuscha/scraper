"""Record validation (docs/DATA_MODEL.md §7).

:func:`validate_record` runs inside the write transaction on the normalised new state
of a record. Problems with the input are collected and raised together as a
``validation_error`` (400); state conflicts raise their own 409 errors afterwards
(``reference_deleted``, ``unique_violation``, ``fixed_code``).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mdt.db.models import Service, VocabularyTerm
from mdt.domain.actor import Actor
from mdt.domain.dates import parse_partial_date
from mdt.domain.errors import (
    FixedCodeError,
    Problems,
    ReferenceDeletedError,
    UniqueViolationError,
)
from mdt.domain.labels import ref_info
from mdt.domain.normalize import is_empty
from mdt.domain.records import Row, load_row, table_of
from mdt.domain.registry import ENTITY_TYPES, TABLE_TYPES, EntityTypeSpec, type_of_id
from mdt.domain.vocab import TermIndex, is_fixed_term

_DIMENSION_RE = re.compile(r"^dimension:D[1-4]$")
#: Reference fields that may point to deleted rows.
DELETED_REFS_ALLOWED = frozenset({("comment", "subject_id"), ("comment", "parent_id")})
#: CODEBOOK §2.3: the evidence of a verified field quotes the source verbatim.
EVIDENCE_QUOTE_MESSAGE = (
    "Verification needs evidence that quotes the source verbatim; add the quote to the "
    "evidence first"
)
#: CODEBOOK §2.8: excluded documents carry an exclusion reason, and only they do.
SCREENING_REASON_REQUIRED = "is required when the document is excluded"
SCREENING_REASON_ONLY_EXCLUDED = "is allowed only for excluded documents"


def verification_rests_on(session: Session, evidence: Mapping[str, Any]) -> bool:
    """True if the subject of an evidence row has the evidence's target field verified
    with exactly this evidence (``field_meta[<field>]``: ``verified`` and its ID),
    whatever the subject's deletion state."""
    target, subject_id = evidence.get("target"), evidence.get("subject_id")
    if not isinstance(target, str) or not target.startswith("field:") or not subject_id:
        return False
    subject_type = type_of_id(subject_id)
    if subject_type is None or not ENTITY_TYPES[subject_type].curated:
        return False
    subject = load_row(session, ENTITY_TYPES[subject_type], subject_id)
    if subject is None:
        return False
    entry = (subject.get("field_meta") or {}).get(target.removeprefix("field:")) or {}
    return entry.get("verified") == "verified" and entry.get("evidence_id") == evidence["id"]


@dataclass(frozen=True)
class WriteWarning:
    """A warning returned with a successful write (API §1.3)."""

    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """``{code, message, field}``."""
        return {"code": self.code, "message": self.message, "field": self.field}


@dataclass
class RecordCheck:
    """The state of one record being written.

    ``current`` and ``new`` hold every stored field in API representation (``current``
    is None on create). ``assigned`` are the fields this write sets: the provided and
    computed fields on create, the changed fields on update. ``provided`` is the
    normalised payload as submitted.
    """

    session: Session
    spec: EntityTypeSpec
    actor: Actor
    terms: TermIndex
    entity_id: str
    current: dict[str, Any] | None
    new: dict[str, Any]
    assigned: frozenset[str]
    provided: Mapping[str, Any]
    note: str | None
    warnings: list[WriteWarning] = field(default_factory=list)

    @property
    def creating(self) -> bool:
        """True when the record is being created."""
        return self.current is None

    def touches(self, *names: str) -> bool:
        """True if this write assigns any of ``names``."""
        return any(name in self.assigned for name in names)


def ref_row(session: Session, ref_id: str) -> tuple[str, Row] | None:
    """The type and row of any referenced ID, or None if it does not exist."""
    entity_type = type_of_id(ref_id)
    if entity_type is None:
        return None
    row = load_row(session, ENTITY_TYPES[entity_type], ref_id)
    return (entity_type, row) if row is not None else None


def validate_record(check: RecordCheck) -> None:
    """Validate the new state; raise the first applicable error."""
    problems = Problems()
    _check_required(check, problems)
    _check_constraints(check, problems)
    _check_vocab_codes(check, problems)
    deleted_refs = _check_references(check, problems)
    rule = _TYPE_RULES.get(check.spec.name)
    if rule is not None:
        rule(check, problems)
    _check_verification_note(check, problems)
    problems.raise_if_any()
    if deleted_refs:
        field_name, ref_id = deleted_refs[0]
        info = ref_info(check.session, ref_id)
        raise ReferenceDeletedError(
            field_name,
            ref_id,
            info.type if info else type_of_id(ref_id) or "",
            info.label if info else None,
        )
    check_unique(check.session, check.spec, check.entity_id, check.new, check.assigned)
    if check.spec.name == "vocabulary_term" and check.actor.channel != "seed":
        _check_fixed_codes(check)


# --------------------------------------------------------------------------------------
# Generic checks
# --------------------------------------------------------------------------------------


def _check_required(check: RecordCheck, problems: Problems) -> None:
    for spec in check.spec.stored_fields:
        if spec.required and is_empty(check.new.get(spec.name)):
            problems.add(spec.name, "is required")


def _check_constraints(check: RecordCheck, problems: Problems) -> None:
    for constraint in check.spec.constraints:
        names = constraint.get("one_of_required")
        if names and all(is_empty(check.new.get(name)) for name in names):
            for name in names:
                problems.add(name, f"At least one of {'/'.join(names)} is required")


def _check_vocab_codes(check: RecordCheck, problems: Problems) -> None:
    for spec in check.spec.stored_fields:
        if spec.type not in ("vocab", "vocab_list") or spec.name not in check.assigned:
            continue
        assert spec.vocabulary is not None
        value = check.new.get(spec.name)
        codes = list(enumerate(value or [])) if spec.type == "vocab_list" else [(None, value)]
        current = check.current.get(spec.name) if check.current else None
        kept = set(current) if isinstance(current, list) else ({current} if current else set())
        terms = check.terms.terms(spec.vocabulary)
        for index, code in codes:
            if code is None:
                continue
            path = spec.name if index is None else f"{spec.name}[{index}]"
            term = terms.get(code)
            if term is None:
                problems.add(path, f"is not a code of the vocabulary {spec.vocabulary}")
            elif not term.active and code not in kept:
                if check.actor.channel == "restore":
                    check.warnings.append(
                        WriteWarning(
                            "inactive_code",
                            "An inactive code was restored; it cannot be newly assigned.",
                            spec.name,
                        )
                    )
                else:
                    problems.add(path, "is an inactive code")


def _check_references(check: RecordCheck, problems: Problems) -> list[tuple[str, str]]:
    """Missing references → problems; references to deleted rows are returned."""
    deleted: list[tuple[str, str]] = []
    for spec in check.spec.stored_fields:
        if spec.type != "ref" or spec.name not in check.assigned:
            continue
        value = check.new.get(spec.name)
        if value is None or (check.current is not None and check.current.get(spec.name) == value):
            continue
        found = ref_row(check.session, value)
        if found is None:
            problems.add(spec.name, "refers to a record that does not exist")
        elif found[1]["deleted_at"] is not None and (
            (check.spec.name, spec.name) not in DELETED_REFS_ALLOWED
        ):
            deleted.append((spec.name, value))
    if check.spec.has_field("links") and "links" in check.assigned:
        before = {link["subject_id"] for link in (check.current or {}).get("links") or []}
        for index, link in enumerate(check.new.get("links") or []):
            if link["subject_id"] in before:
                continue
            found = ref_row(check.session, link["subject_id"])
            if found is None:
                problems.add(f"links[{index}].subject_id", "refers to a record that does not exist")
            elif found[1]["deleted_at"] is not None:
                deleted.append(("links", link["subject_id"]))
    return deleted


def _check_verification_note(check: RecordCheck, problems: Problems) -> None:
    if not check.spec.curated or "verification_status" not in check.assigned:
        return
    if check.new.get("verification_status") in ("verified", "disputed") and not check.note:
        problems.add(
            "note", "A note is required when the verification status is verified or disputed"
        )


def check_unique(
    session: Session,
    spec: EntityTypeSpec,
    entity_id: str,
    values: Mapping[str, Any],
    assigned: frozenset[str] | None = None,
) -> None:
    """Raise :class:`UniqueViolationError` if a unique value is used by another row.

    ``assigned=None`` checks every unique field (used by undelete).
    """
    table = table_of(spec)
    for field_spec in spec.stored_fields:
        if field_spec.unique is None or is_empty(values.get(field_spec.name)):
            continue
        if assigned is not None and field_spec.name not in assigned:
            continue
        query = select(table.c.id).where(
            table.c[field_spec.name] == values[field_spec.name], table.c.id != entity_id
        )
        if field_spec.unique == "live":
            query = query.where(table.c.deleted_at.is_(None))
        existing = session.execute(query.limit(1)).scalar()
        if existing is not None:
            raise UniqueViolationError(field_spec.name, _existing(session, existing))
    if spec.name == "vocabulary_term" and (assigned is None or "code" in assigned):
        existing = session.execute(
            select(VocabularyTerm.id).where(
                VocabularyTerm.vocabulary == values.get("vocabulary"),
                VocabularyTerm.code == values.get("code"),
                VocabularyTerm.id != entity_id,
            )
        ).scalar()
        if existing is not None:
            raise UniqueViolationError("code", _existing(session, existing))


def _existing(session: Session, entity_id: str) -> dict[str, Any] | None:
    info = ref_info(session, entity_id)
    if info is None:
        return None
    return {"id": info.id, "label": info.label, "deleted": info.deleted}


# --------------------------------------------------------------------------------------
# Entity-specific rules
# --------------------------------------------------------------------------------------


def _project_rules(check: RecordCheck, problems: Problems) -> None:
    scope_set = check.creating or "in_paper_scope" in check.assigned
    if scope_set and is_empty(check.provided.get("scope_note")):
        problems.add(
            "scope_note",
            "A scope note is required in the same change when the scope is set or changed",
        )


def _service_rules(check: RecordCheck, problems: Problems) -> None:
    parent = check.new.get("parent_service_id")
    if parent and check.touches("parent_service_id", "project_id"):
        if parent == check.entity_id:
            problems.add("parent_service_id", "A service cannot be its own parent")
        else:
            parent_row = load_row(check.session, ENTITY_TYPES["service"], parent)
            if parent_row is not None and parent_row["project_id"] != check.new.get("project_id"):
                problems.add(
                    "parent_service_id", "The parent service must belong to the same project"
                )
            if _creates_cycle(check.session, check.entity_id, parent):
                problems.add("parent_service_id", "The parent service would create a cycle")
    if not check.creating and "project_id" in check.assigned:
        children = check.session.execute(
            select(func.count())
            .select_from(Service)
            .where(Service.parent_service_id == check.entity_id, Service.deleted_at.is_(None))
        ).scalar_one()
        if children:
            problems.add(
                "project_id", "The project cannot change while the service has child services"
            )


def _creates_cycle(session: Session, entity_id: str, parent: str) -> bool:
    seen: set[str] = set()
    current: str | None = parent
    while current is not None and current not in seen:
        if current == entity_id:
            return True
        seen.add(current)
        current = session.execute(
            select(Service.parent_service_id).where(Service.id == current)
        ).scalar()
    return False


def _event_rules(check: RecordCheck, problems: Problems) -> None:
    if not check.touches("date", "date_basis", "event_type"):
        return
    event_type = check.new.get("event_type")
    basis = check.new.get("date_basis")
    if check.new.get("date") and not basis:
        problems.add("date_basis", "is required when a date is set")
    if event_type == "first_archived" and basis != "archive_upper_bound":
        problems.add("date_basis", "must be archive_upper_bound for first_archived events")
    if basis == "archive_upper_bound" and event_type != "first_archived":
        problems.add(
            "date_basis",
            "archive_upper_bound is allowed only for first_archived events; record an archive "
            "capture as a separate first_archived event",
        )


def _document_rules(check: RecordCheck, problems: Problems) -> None:
    if (
        check.touches("published", "published_basis")
        and check.new.get("published")
        and not check.new.get("published_basis")
    ):
        problems.add("published_basis", "is required when a publication date is set")
    if check.touches("screening_status", "screening_reason"):
        excluded = check.new.get("screening_status") == "excluded"
        if excluded and not check.new.get("screening_reason"):
            problems.add("screening_reason", SCREENING_REASON_REQUIRED)
        elif not excluded and check.new.get("screening_reason"):
            problems.add("screening_reason", SCREENING_REASON_ONLY_EXCLUDED)
    if (
        check.actor.channel == "ui"
        and check.touches("url", "retrieved_at")
        and check.new.get("url")
        and not check.new.get("retrieved_at")
    ):
        problems.add("retrieved_at", "is required when a URL is set")


def _participation_rules(check: RecordCheck, problems: Problems) -> None:
    start, end = check.new.get("start"), check.new.get("end")
    if not (start and end and check.touches("start", "end")):
        return
    if parse_partial_date(end).start < parse_partial_date(start).start:
        problems.add("end", "must not be before the start")


def _relation_rules(check: RecordCheck, problems: Problems) -> None:
    if check.new.get("from_id") and check.new.get("from_id") == check.new.get("to_id"):
        problems.add("to_id", "must differ from from_id")


def _evidence_rules(check: RecordCheck, problems: Problems) -> None:
    target = check.new.get("target")
    if target and check.touches("target", "subject_id"):
        _check_evidence_target(check, target, problems)
    if (
        (check.creating or check.touches("document_id", "retrieved_at"))
        and not check.new.get("document_id")
        and not check.new.get("retrieved_at")
    ):
        problems.add("retrieved_at", "is required when no document is cited")
    char_start, char_end = check.new.get("char_start"), check.new.get("char_end")
    for name, value in (("char_start", char_start), ("char_end", char_end)):
        if value is not None and value < 0:
            problems.add(name, "must not be negative")
    if char_start is not None and char_end is not None and char_end < char_start:
        problems.add("char_end", "must not be before char_start")
    if (
        not check.creating
        and "quote" in check.assigned
        and not check.new.get("quote")
        and verification_rests_on(check.session, {**check.new, "id": check.entity_id})
    ):
        problems.add(
            "quote",
            "A field is verified with this evidence; its verbatim quote cannot be removed",
        )


def _check_evidence_target(check: RecordCheck, target: str, problems: Problems) -> None:
    if target == "entity" or _DIMENSION_RE.fullmatch(target):
        return
    if not target.startswith("field:"):
        problems.add("target", "must be entity, field:<field name> or dimension:D1 … D4")
        return
    subject_type = type_of_id(check.new.get("subject_id") or "")
    name = target.removeprefix("field:")
    if subject_type is None:
        return
    subject_spec = ENTITY_TYPES[subject_type]
    if not subject_spec.has_field(name):
        problems.add("target", "names a field that the subject's type does not have")
        return
    target_field = subject_spec.field(name)
    if not target_field.tracked or target_field.system:
        problems.add("target", "must name a tracked field that is not set by the system")


def _vocabulary_term_rules(check: RecordCheck, problems: Problems) -> None:
    vocabulary = check.new.get("vocabulary")
    if check.creating and vocabulary and check.terms.vocabulary(vocabulary) is None:
        problems.add("vocabulary", "is not a known vocabulary")
    attributes = check.new.get("attributes")
    if attributes is not None and not isinstance(attributes, dict):
        problems.add("attributes", "must be an object")
    replaced_by = check.new.get("replaced_by")
    if replaced_by and check.touches("replaced_by", "active"):
        if check.new.get("active"):
            problems.add("replaced_by", "is allowed only for inactive terms")
        elif replaced_by == check.new.get("code"):
            problems.add("replaced_by", "must differ from the term's own code")
        else:
            target = check.terms.term(str(vocabulary), replaced_by)
            if target is None or not target.active:
                problems.add("replaced_by", "must be an active code of the same vocabulary")


def _check_fixed_codes(check: RecordCheck) -> None:
    """Fixed codes cannot be added or deactivated; ``attributes.fixed`` is set only by
    the codebook files (channel seed)."""
    vocabulary = check.terms.vocabulary(str(check.new.get("vocabulary")))
    new_attributes = (
        check.new.get("attributes") if isinstance(check.new.get("attributes"), dict) else None
    )
    if check.current is None:
        if is_fixed_term(vocabulary, new_attributes):
            raise FixedCodeError("Terms cannot be added to a vocabulary with fixed codes")
        return
    old_attributes = (
        check.current.get("attributes")
        if isinstance(check.current.get("attributes"), dict)
        else None
    )
    deactivated = (
        "active" in check.assigned and check.current.get("active") and not check.new.get("active")
    )
    if deactivated and is_fixed_term(vocabulary, old_attributes):
        raise FixedCodeError("Fixed codes cannot be deactivated")
    old_fixed = bool(old_attributes and old_attributes.get("fixed") is True)
    new_fixed = bool(new_attributes and new_attributes.get("fixed") is True)
    if "attributes" in check.assigned and old_fixed != new_fixed:
        raise FixedCodeError("The fixed attribute of a term is set by the codebook files only")


def _saved_view_rules(check: RecordCheck, problems: Problems) -> None:
    entity_type = check.new.get("entity_type")
    if entity_type and entity_type not in TABLE_TYPES:
        problems.add("entity_type", f"must be one of {', '.join(TABLE_TYPES)}")
    query = check.new.get("query")
    if query and query.startswith("?"):
        problems.add("query", "must not start with ?")


_TYPE_RULES: dict[str, Callable[[RecordCheck, Problems], None]] = {
    "project": _project_rules,
    "service": _service_rules,
    "event": _event_rules,
    "document": _document_rules,
    "participation": _participation_rules,
    "relation": _relation_rules,
    "evidence": _evidence_rules,
    "vocabulary_term": _vocabulary_term_rules,
    "saved_view": _saved_view_rules,
}
