"""Tabular imports of CSV and XLSX files (docs/COLLECTORS.md §9, docs/DATA_MODEL.md §17.1).

The workflow: an uploaded file (an upload snapshot) is previewed (:func:`preview_import`),
planned with a mapping (:func:`dry_run_import`, writes nothing) and run (:func:`run_import`).
Mapping and plan are not stored; only an import that was run is (``import_run``). Files are
read by :mod:`.files`, mappings and cells checked by :mod:`.mapping`.

**Data rules (DATA_MODEL §17.1):** writes use channel ``import`` with the actor
``import:<file_label>`` (``<filename>#<sha256[0:12]>``), so values get ``src =
import:<file_label>`` and are locked; every revision has ``batch_id`` = the import's ID.
An existing record's field is written only if the value differs and the field has no
provenance entry, or an unlocked one (a collector value), or one written by an import and
not touched by a person since; any other difference is a **conflict** (reason ``manual``,
``seed``, ``verified`` or ``restored``) and stays as it is. Empty cells never clear a field.
Each row is its own write unit, made with the machinery of ``apply_change``
(:mod:`mdt.domain.writes`), so the lock decision and the write see the same row; a dry run
makes the same unit and rolls it back.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from mdt.collectors.store import SnapshotRecord
from mdt.config import Settings
from mdt.db.engine import BEGIN_MODE_OPTION
from mdt.db.models import ImportRun
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.errors import (
    DomainError,
    EntityDeletedError,
    NotFoundError,
    ReferenceDeletedError,
    UniqueViolationError,
    ValidationError,
)
from mdt.domain.ids import new_id
from mdt.domain.normalize import ValueProblem, is_empty, values_equal
from mdt.domain.records import Row, field_meta_of, load_links, load_row, stored_values, table_of
from mdt.domain.registry import EntityTypeSpec, type_of_id
from mdt.domain.urls import UrlError, canonical_url
from mdt.domain.writes import WriteUnit, clean_note, create_record, normalize_changes, update_record
from mdt.importers.files import Table, load_upload, read_table
from mdt.importers.mapping import (
    ID_KEY,
    CellParser,
    check_mapping,
    importable_fields,
    key_fields,
    suggest_mapping,
    table_spec,
)

log = logging.getLogger("mdt.importers")

PREVIEW_ROWS = 20
MAX_PLAN_ROWS = 500
RowAction = Literal["create", "update", "unchanged", "error"]


# --------------------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------------------


@dataclass
class RowResult:
    """The plan (or result) of one row (docs/COLLECTORS.md §9.4)."""

    row: int
    action: RowAction
    id: str | None = None
    changes: dict[str, list[Any]] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, list[str]] = field(default_factory=dict)

    def as_api(self) -> dict[str, Any]:
        """The row item of a plan."""
        return {
            "row": self.row,
            "action": self.action,
            "id": self.id,
            "changes": self.changes,
            "conflicts": self.conflicts,
            "errors": self.errors,
        }


@dataclass
class Plan:
    """The rows of a dry run or an import run."""

    rows: list[RowResult] = field(default_factory=list)

    @property
    def stats(self) -> dict[str, int]:
        """Rows by action; ``conflicts`` counts the rows with at least one conflict."""
        counts = {"rows": len(self.rows), "create": 0, "update": 0, "unchanged": 0}
        for row in self.rows:
            if row.action != "error":
                counts[row.action] += 1
        counts["conflicts"] = sum(1 for row in self.rows if row.conflicts)
        counts["errors"] = sum(1 for row in self.rows if row.action == "error")
        return counts

    def ordered(self) -> list[RowResult]:
        """Errors first, then rows with conflicts, then the rest (each by row number)."""
        return sorted(
            self.rows,
            key=lambda row: (0 if row.action == "error" else 1 if row.conflicts else 2, row.row),
        )

    def as_api(self) -> dict[str, Any]:
        """``{stats, rows}`` with at most 500 row items."""
        return {
            "stats": self.stats,
            "rows": [row.as_api() for row in self.ordered()[:MAX_PLAN_ROWS]],
        }

    def problems(self) -> list[dict[str, Any]]:
        """The rows with errors or conflicts (``import_run.errors``, at most 500)."""
        return [row.as_api() for row in self.ordered() if row.action == "error" or row.conflicts][
            :MAX_PLAN_ROWS
        ]


def conflict_reason(entry: Mapping[str, Any] | None) -> str | None:
    """None if an import may overwrite the field (no entry, an unlocked collector value,
    or an untouched import value), else the conflict reason (DATA_MODEL §17.1)."""
    if entry is None or not entry.get("locked"):
        return None
    verified = entry.get("verified") or "unverified"
    restored = entry.get("restored_from_version") is not None
    if (
        str(entry.get("by") or "").startswith("import:")
        and verified == "unverified"
        and not restored
    ):
        return None
    if verified != "unverified":
        return "verified"
    if restored:
        return "restored"
    if entry.get("by") == "seed" or entry.get("src") == "seed":
        return "seed"
    return "manual"


def _error_details(exc: DomainError) -> dict[str, list[str]]:
    if isinstance(exc, ValidationError):
        return {path: list(messages) for path, messages in (exc.details or {}).items()}
    details = exc.details or {}
    if isinstance(exc, UniqueViolationError):
        return {str(details.get("field")): ["is already used by another record"]}
    if isinstance(exc, ReferenceDeletedError):
        return {str(details.get("field")): ["references a deleted record"]}
    return {"row": [exc.message]}


@contextmanager
def _rolled_back_unit(session: Session) -> Iterator[Session]:
    """A write unit (``BEGIN IMMEDIATE``) that is always rolled back: a dry run makes the
    same writes as the run and discards them."""
    if session.in_transaction():
        session.commit()
    session.connection(execution_options={BEGIN_MODE_OPTION: "IMMEDIATE"})
    try:
        yield session
    finally:
        session.rollback()


@dataclass(frozen=True)
class _Job:
    """What every row of one import shares."""

    spec: EntityTypeSpec
    actor: Actor
    mapping: Mapping[str, str]
    key_field: str | None
    columns: Mapping[str, int]
    note: str | None
    batch_id: str | None
    write: bool


class _RowError(Exception):
    def __init__(self, errors: dict[str, list[str]]) -> None:
        super().__init__("row error")
        self.errors = errors


def _cells(
    job: _Job, parser: CellParser, cells: Sequence[str]
) -> tuple[dict[str, Any], str | None]:
    values: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    key_id: str | None = None
    width = len(job.columns)
    extra = [cell for cell in cells[width:] if cell.strip()]
    if extra:
        errors["row"] = ["has more cells than the header has columns"]
    for column, target in job.mapping.items():
        index = job.columns[column]
        text = cells[index] if index < len(cells) else ""
        if not text.strip():
            continue
        if target == ID_KEY:
            key_id = text.strip()
            continue
        try:
            values[target] = parser.parse(job.spec.field(target), text)
        except ValueProblem as exc:
            errors.setdefault(target, []).append(str(exc))
    if errors:
        raise _RowError(errors)
    return values, key_id


def _find(session: Session, job: _Job, values: Mapping[str, Any], key_id: str | None) -> Row | None:
    """The record a row updates (None: the row creates one)."""
    spec = job.spec
    if job.key_field == ID_KEY:
        if key_id is None:
            return None
        row = load_row(session, spec, key_id) if type_of_id(key_id) == spec.name else None
        if row is None:
            raise _RowError({ID_KEY: ["no record of this type has this ID"]})
        return row
    if job.key_field is None or is_empty(values.get(job.key_field)):
        return None
    table = table_of(spec)
    if job.key_field == "slug":
        found = session.execute(select(table.c.id).where(table.c.slug == values["slug"])).scalar()
    else:
        try:
            canonical = canonical_url(str(values["url"]))
        except UrlError as exc:
            raise _RowError({"url": [str(exc)]}) from exc
        found = session.execute(
            select(table.c.id)
            .where(table.c.canonical_url == canonical)
            .order_by(table.c.deleted_at.is_not(None), table.c.id)
        ).scalar()
    return None if found is None else load_row(session, spec, str(found))


def _update(
    unit: WriteUnit, job: _Job, row: Row, values: dict[str, Any], result: RowResult
) -> None:
    spec = job.spec
    if row["deleted_at"] is not None:
        raise EntityDeletedError(row["deleted_at"], row["deleted_by"])
    provided = normalize_changes(
        unit,
        {name: value for name, value in values.items() if not spec.field(name).create_only},
        creating=False,
    )
    links = load_links(unit.session, [row["id"]])[row["id"]] if spec.has_field("links") else None
    current = stored_values(spec, row, links)
    meta = field_meta_of(spec, row)
    changes: dict[str, Any] = {}
    for name, value in provided.items():
        if values_equal(spec.field(name), current[name], value):
            continue
        reason = conflict_reason(meta.get(name))
        if reason is None:
            changes[name] = value
            result.changes[name] = [current[name], value]
        else:
            result.conflicts.append(
                {"field": name, "current": current[name], "new": value, "reason": reason}
            )
    if "in_paper_scope" in changes and "scope_note" not in changes and "scope_note" in provided:
        # The scope rule needs the reason in the same change. The imported note equals the
        # current one or is a conflict, which is never written (§17.1): the current note
        # goes along, as in the seed and a merge.
        changes["scope_note"] = current["scope_note"]
    result.id = row["id"]
    if not changes:
        result.action = "unchanged"
        return
    update_record(unit, row, changes, note=job.note, batch_id=job.batch_id)
    result.action = "update"


def plan_row(
    session: Session, job: _Job, parser: CellParser, number: int, cells: Sequence[str]
) -> RowResult:
    """Plan (and with ``job.write`` apply) one row in its own write unit."""
    result = RowResult(number, "unchanged")
    unit_scope: AbstractContextManager[Session] = (
        write_transaction(session) if job.write else _rolled_back_unit(session)
    )
    try:
        with unit_scope:
            values, key_id = _cells(job, parser, cells)
            unit = WriteUnit.open(session, job.spec, job.actor)
            row = _find(session, job, values, key_id)
            if row is not None:
                _update(unit, job, row, values, result)
                return result
            provided = normalize_changes(unit, values, creating=True)
            created = create_record(unit, provided, note=job.note, batch_id=job.batch_id)
            result.action = "create"
            result.id = created.entity_id if job.write else None
            result.changes = {
                name: [None, value] for name, value in provided.items() if not is_empty(value)
            }
    except _RowError as exc:
        return RowResult(number, "error", errors=exc.errors)
    except EntityDeletedError:
        key = job.key_field or ID_KEY
        return RowResult(
            number, "error", errors={key: ["matches a deleted record (entity_deleted)"]}
        )
    except DomainError as exc:
        return RowResult(number, "error", errors=_error_details(exc))
    return result


# --------------------------------------------------------------------------------------
# Preview, dry run, run
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportRequest:
    """A planned or run import (docs/API.md §7.9)."""

    upload_id: str
    entity_type: str
    sheet: str | None = None
    mapping: Mapping[str, str] = field(default_factory=dict)
    key_field: str | None = None
    note: str | None = None


def preview_import(
    session: Session, settings: Settings, upload_id: Any, entity_type: Any, sheet: str | None = None
) -> dict[str, Any]:
    """Sheets, columns, the first 20 rows, a suggested mapping, the importable fields and
    the key fields of the type. Writes nothing."""
    spec = table_spec(entity_type)
    record, body = load_upload(session, settings, upload_id)
    table = read_table(record, body, sheet)
    width = len(table.columns)
    preview = [
        [*cells[:width], *([""] * (width - len(cells)))] for _, cells in table.rows[:PREVIEW_ROWS]
    ]
    return {
        "sheets": list(table.sheets) if table.sheets is not None else None,
        "columns": list(table.columns),
        "preview": preview,
        "suggested_mapping": suggest_mapping(spec.name, table.columns),
        "importable_fields": importable_fields(spec.name),
        "key_fields": key_fields(spec.name),
    }


def _prepare(
    session: Session,
    settings: Settings,
    request: ImportRequest,
    *,
    write: bool,
    batch_id: str | None,
) -> tuple[SnapshotRecord, Table, _Job]:
    """Read the file, check the mapping and describe the job (400 on any problem)."""
    spec = table_spec(request.entity_type)
    record, body = load_upload(session, settings, request.upload_id)
    table = read_table(record, body, request.sheet)
    mapping = check_mapping(spec.name, table.columns, request.mapping, request.key_field)
    job = _Job(
        spec=spec,
        actor=Actor.importer(file_label(record)),
        mapping=mapping,
        key_field=request.key_field,
        columns={name: index for index, name in enumerate(table.columns)},
        note=clean_note(request.note),
        batch_id=batch_id,
        write=write,
    )
    return record, table, job


def file_label(record: SnapshotRecord) -> str:
    """``<filename>#<sha256[0:12]>``: the provenance ``import:<file_label>``."""
    return f"{record.filename}#{record.sha256[:12]}"


def _execute(session: Session, table: Table, job: _Job, plan: Plan) -> None:
    parser = CellParser(session)
    for number, cells in table.rows:
        plan.rows.append(plan_row(session, job, parser, number, cells))


def dry_run_import(session: Session, settings: Settings, request: ImportRequest) -> Plan:
    """The plan of an import: every row decided as the run would, nothing written."""
    _, table, job = _prepare(session, settings, request, write=False, batch_id=None)
    plan = Plan()
    _execute(session, table, job, plan)
    return plan


@dataclass(frozen=True)
class ImportResult:
    """The stored ``import_run`` (API representation) and the result plan."""

    import_run: dict[str, Any]
    plan: Plan


def run_import(session: Session, settings: Settings, request: ImportRequest) -> ImportResult:
    """Run an import: each row its own write unit on channel ``import``, all revisions with
    ``batch_id`` = the import's ID; the ``import_run`` row is stored at the end (``done``,
    or ``failed`` after an unexpected error, the rows written before it staying). A file
    or mapping that cannot be used is refused with 400 before anything is written."""
    import_id = new_id("imp")
    record, table, job = _prepare(session, settings, request, write=True, batch_id=import_id)
    created_at = utc_now()
    plan = Plan()
    status, error = "done", None
    try:
        _execute(session, table, job, plan)
    except Exception as exc:  # a fatal error: record it, keep what was written
        log.exception("import %s failed", import_id)
        status, error = "failed", f"unexpected error: {type(exc).__name__}"
        if session.in_transaction():
            session.rollback()
    values = {
        "id": import_id,
        "upload_id": record.id,
        "filename": record.filename or "",
        "file_label": file_label(record),
        "entity_type": job.spec.name,
        "sheet": table.sheet,
        "status": status,
        "mapping": dict(job.mapping),
        "key_field": job.key_field,
        "note": job.note,
        "stats": plan.stats,
        "errors": plan.problems(),
        "error": error,
        "created_at": created_at,
        "finished_at": utc_now(),
    }
    with write_transaction(session):
        session.execute(insert(ImportRun).values(**values))
    return ImportResult(import_payload(values), plan)


#: The keys of the ``ImportRun`` object (docs/API.md §7.9), the columns of ``import_run``.
IMPORT_KEYS = (
    "id",
    "upload_id",
    "filename",
    "file_label",
    "entity_type",
    "sheet",
    "status",
    "mapping",
    "key_field",
    "note",
    "stats",
    "errors",
    "error",
    "created_at",
    "finished_at",
)


def import_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    """The ``ImportRun`` object of the API."""
    return {key: values.get(key) for key in IMPORT_KEYS}


def _row_payload(row: ImportRun) -> dict[str, Any]:
    return {key: getattr(row, key) for key in IMPORT_KEYS}


def list_imports(session: Session, *, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Stored imports, newest first."""
    with read_transaction(session):
        total = int(session.scalar(select(func.count()).select_from(ImportRun)) or 0)
        rows = session.scalars(
            select(ImportRun)
            .order_by(ImportRun.created_at.desc(), ImportRun.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [_row_payload(row) for row in rows], total


def get_import(session: Session, import_id: str) -> dict[str, Any]:
    """One stored import (404 if unknown)."""
    with read_transaction(session):
        row = session.get(ImportRun, import_id)
        if row is None:
            raise NotFoundError()
        return _row_payload(row)
