"""Exports of a list view as CSV or XLSX (docs/API.md §1.4 and §5).

:func:`start_export` validates the request, takes the single export slot (``429 busy``
while another export runs), opens a dedicated read session and checks the row count
(``400 export_too_large`` over :data:`MAX_EXPORT_ROWS`). The returned
:class:`ExportJob` then streams CSV (:meth:`ExportJob.iter_csv`) or writes XLSX in
openpyxl's write-only mode (:meth:`ExportJob.write_xlsx`); both release the slot and the
session when they finish, and :meth:`ExportJob.close` does so on any other path.

Spreadsheet safety: XLSX string values are always string cells (never formulas or
errors), with illegal characters replaced and over-long strings truncated. CSV string
cells that start with ``= + - @``, tab, CR or LF get a leading apostrophe; number,
boolean and date columns are never changed.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Final, Literal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ERROR_CODES, ILLEGAL_CHARACTERS_RE, Cell
from openpyxl.styles import Font
from openpyxl.worksheet._write_only import WriteOnlyWorksheet
from sqlalchemy import select
from sqlalchemy.orm import Session

from mdt.db.models import VocabularyTerm
from mdt.domain.dates import parse_partial_date
from mdt.domain.errors import BusyError, ExportTooLargeError, ValidationError
from mdt.domain.labels import format_number, ref_infos
from mdt.domain.listquery import (
    QueryParams,
    SortKey,
    last_param,
    param_pairs,
    parse_scope,
    parse_sort_param,
    split_list,
)
from mdt.domain.query import Selection, iter_id_chunks, select_scope
from mdt.domain.records import api_value, load_links, table_of
from mdt.domain.registry import EntityTypeSpec, FieldSpec
from mdt.domain.serialize import derived_payload, derived_rows, generic_spec, virtual_values

MAX_EXPORT_ROWS: Final = 200_000
FORMATS: Final = ("csv", "xlsx")
MEDIA_TYPES: Final = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
XLSX_MAX_CHARS: Final = 32_767
TRUNCATION_SUFFIX: Final = " [truncated]"
#: Texts that openpyxl would store as an error value instead of a string.
XLSX_ERROR_VALUES: Final = frozenset(ERROR_CODES)
#: First characters that spreadsheet programs read as a formula (CSV only).
FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r", "\n")
LIST_SEPARATOR: Final = "; "
CHUNK_SIZE: Final = 500
ID_COLUMN: Final = "id"

ColumnKind = Literal["string", "number", "bool", "date"]
Item = Mapping[str, Any]

_SLOT = threading.Lock()


@dataclass(frozen=True)
class Column:
    """One output column: header (a registry name or a derived name), kind and how to
    read the value from a serialised item."""

    header: str
    kind: ColumnKind
    value: Callable[[Item], Any]


# --------------------------------------------------------------------------------------
# Columns (API §5)
# --------------------------------------------------------------------------------------

#: Derived values exported next to each derived field: (suffix, key in ``derived``).
_DERIVED_EXTRAS: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "launch": (("basis", "launch_basis"), ("event_id", "launch_event_id")),
    "existed_by": (("event_id", "existed_by_event_id"),),
    "period": (("reason", "period_reason"),),
    "war_trajectory": (("reason", "trajectory_reason"), ("event_id", "trajectory_event_id")),
    "portfolio_entry": (("participation_id", "portfolio_entry_participation_id"),),
}


def exportable(field: FieldSpec) -> bool:
    """Fields that have a value per row (filter-only and detail-only fields do not);
    ``/api/meta`` exposes the same flag, so the UI offers only these columns."""
    return field.exportable


def _join(values: Iterable[Any]) -> str:
    return LIST_SEPARATOR.join(str(value) for value in values)


def _partial_date_part(value: str | None, part: str) -> str | None:
    if not value:
        return None
    parsed = parse_partial_date(value)
    return {"start": parsed.start_iso, "end": parsed.end_iso, "precision": parsed.precision}[part]


def _compact_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class _Labels:
    """Vocabulary labels (``label_en``) for the columns of one export."""

    def __init__(self) -> None:
        self.terms: dict[tuple[str, str], str] = {}

    def load(self, session: Session, vocabularies: Iterable[str]) -> None:
        names = set(vocabularies)
        if not names:
            return
        rows = session.execute(
            select(VocabularyTerm.vocabulary, VocabularyTerm.code, VocabularyTerm.label_en).where(
                VocabularyTerm.vocabulary.in_(names)
            )
        )
        self.terms = {(vocabulary, code): label for vocabulary, code, label in rows}

    def label(self, vocabulary: str, code: str | None) -> str | None:
        if code is None:
            return None
        return self.terms.get((vocabulary, code), code)


def _ref_label(item: Item, key: str) -> str | None:
    ref = item["refs"].get(key)
    return ref["label"] if ref else None


def _derived_columns(field: FieldSpec, labels: _Labels) -> list[Column]:
    name = field.name
    header = f"derived_{name}"

    def derived(key: str) -> Callable[[Item], Any]:
        return lambda item: (item.get("derived") or {}).get(key)

    columns: list[Column]
    if field.type == "partial_date":
        columns = [
            Column(header, "date", derived(name)),
            Column(f"{header}_start", "date", derived(f"{name}_start")),
            Column(f"{header}_end", "date", derived(f"{name}_end")),
            Column(f"{header}_precision", "string", derived(f"{name}_precision")),
        ]
    elif field.type == "vocab":
        vocabulary = field.vocabulary or name
        columns = [
            Column(header, "string", derived(name)),
            Column(
                f"{header}_label",
                "string",
                lambda item: labels.label(vocabulary, derived(name)(item)),
            ),
        ]
    else:
        columns = [Column(header, "date", derived(name))]
    columns.extend(
        Column(f"{header}_{suffix}", "string", derived(key))
        for suffix, key in _DERIVED_EXTRAS.get(name, ())
    )
    return columns


def _system_kind(field: FieldSpec) -> ColumnKind:
    if field.type == "datetime":
        return "date"
    if field.type == "int":
        return "number"
    return "string"


def _field_columns(field: FieldSpec, labels: _Labels) -> list[Column]:
    """The columns of one registry field (API §5)."""
    name = field.name
    if field.derived:
        return _derived_columns(field, labels)
    if field.virtual:
        kind: ColumnKind = "bool" if field.type == "bool" else "number"
        return [Column(name, kind, lambda item: item["virtual"].get(name))]
    if field.system_column:
        return [Column(name, _system_kind(field), lambda item: item[name])]

    def value(item: Item) -> Any:
        return item["fields"].get(name)

    kind_of = field.type
    if kind_of == "bool":
        return [Column(name, "bool", value)]
    if kind_of in ("int", "number"):
        return [Column(name, "number", value)]
    if kind_of in ("date", "datetime"):
        return [Column(name, "date", value)]
    if kind_of == "partial_date":
        return [
            Column(name, "date", value),
            Column(f"{name}_start", "date", lambda item: _partial_date_part(value(item), "start")),
            Column(f"{name}_end", "date", lambda item: _partial_date_part(value(item), "end")),
            Column(
                f"{name}_precision",
                "string",
                lambda item: _partial_date_part(value(item), "precision"),
            ),
        ]
    if kind_of in ("url_list", "string_list"):
        return [Column(name, "string", lambda item: _join(value(item) or []))]
    if kind_of == "alias_list":
        return [Column(name, "string", lambda item: _join(a["text"] for a in value(item) or []))]
    if kind_of == "vocab":
        vocabulary = field.vocabulary or name
        return [
            Column(name, "string", value),
            Column(f"{name}_label", "string", lambda item: labels.label(vocabulary, value(item))),
        ]
    if kind_of == "vocab_list":
        list_vocabulary = field.vocabulary or name
        return [
            Column(name, "string", lambda item: _join(value(item) or [])),
            Column(
                f"{name}_label",
                "string",
                lambda item: _join(
                    labels.label(list_vocabulary, code) or code for code in value(item) or []
                ),
            ),
        ]
    if kind_of == "ref":
        return [
            Column(name, "string", value),
            Column(f"{name}_label", "string", lambda item: _ref_label(item, name)),
        ]
    if kind_of == "doc_links":
        return [
            Column(
                name,
                "string",
                lambda item: _compact_json(
                    [
                        {
                            "subject_id": link["subject_id"],
                            "origin": link["origin"],
                            "state": link["state"],
                        }
                        for link in value(item) or []
                    ]
                ),
            ),
            Column(
                f"{name}_label",
                "string",
                lambda item: _join(
                    f"{_ref_label(item, 'links.' + link['subject_id']) or link['subject_id']}"
                    f" ({link['state']})"
                    for link in value(item) or []
                ),
            ),
        ]
    if kind_of == "json":
        return [Column(name, "string", lambda item: _compact_json(value(item)))]
    return [Column(name, "string", value)]


def column_names(spec: EntityTypeSpec, raw: str | None) -> list[str]:
    """The requested ``cols`` (registry names and ``id``), or ``id`` plus the type's
    ``in_list`` fields. Unknown or non-exportable names are a validation error."""
    names = split_list(raw)
    if not names:
        return [ID_COLUMN, *(f.name for f in spec.fields if f.in_list and exportable(f))]
    for name in names:
        if name == ID_COLUMN:
            continue
        field = spec.field_map.get(name)
        if field is None or not exportable(field):
            raise ValidationError.single("cols", "contains an unknown or non-exportable column")
    return names


def build_columns(spec: EntityTypeSpec, names: Sequence[str], labels: _Labels) -> list[Column]:
    """Output columns for the selected names."""
    columns: list[Column] = []
    for name in names:
        if name == ID_COLUMN:
            columns.append(Column(ID_COLUMN, "string", lambda item: item["id"]))
        else:
            columns.extend(_field_columns(spec.field(name), labels))
    return columns


@dataclass(frozen=True)
class ExportNeeds:
    """What the selected columns read. An export loads only this: the table columns of
    the selected stored and system fields, document links, derived rows, the selected
    virtual counts and the labels of the selected references. It never builds
    ``field_meta`` or anything else of a full API item."""

    columns: tuple[str, ...] = ()
    system: tuple[str, ...] = ()
    fields: tuple[FieldSpec, ...] = ()
    virtual: tuple[str, ...] = ()
    derived: bool = False
    ref_fields: tuple[str, ...] = ()
    links: bool = False


def export_needs(spec: EntityTypeSpec, names: Sequence[str]) -> ExportNeeds:
    """The needs of the selected column names (``id`` and registry names)."""
    columns: list[str] = []
    system: list[str] = []
    fields: list[FieldSpec] = []
    virtual: list[str] = []
    ref_fields: list[str] = []
    derived = links = False
    for name in names:
        if name == ID_COLUMN:
            continue
        field = spec.field(name)
        if field.derived:
            derived = True
        elif field.virtual:
            virtual.append(name)
        elif field.system_column:
            system.append(name)
            columns.extend(field.columns)
        else:
            fields.append(field)
            columns.extend(field.columns)
            links = links or field.type == "doc_links"
            if field.type == "ref":
                ref_fields.append(name)
    return ExportNeeds(
        columns=tuple(dict.fromkeys(columns)),
        system=tuple(system),
        fields=tuple(fields),
        virtual=tuple(virtual),
        derived=derived,
        ref_fields=tuple(ref_fields),
        links=links,
    )


def export_items(
    session: Session, spec: EntityTypeSpec, ids: Sequence[str], needs: ExportNeeds
) -> list[dict[str, Any]]:
    """Light items for one chunk of IDs, in the given order: the keys of API items
    (``id``, system columns, ``fields``, ``virtual``, ``derived``, ``refs``) holding
    only what :class:`ExportNeeds` names. The column readers of :func:`build_columns`
    read them like full items."""
    table = table_of(spec)
    statement = select(table.c.id, *(table.c[name] for name in needs.columns))
    found = {
        row["id"]: dict(row)
        for row in session.execute(statement.where(table.c.id.in_(list(ids)))).mappings()
    }
    rows = [found[entity_id] for entity_id in ids if entity_id in found]
    row_ids = [row["id"] for row in rows]
    links = load_links(session, row_ids) if needs.links else {}
    derived = derived_rows(session, row_ids) if needs.derived else {}
    virtual = virtual_values(session, spec, row_ids, needs.virtual) if needs.virtual else {}
    wanted = [row[name] for row in rows for name in needs.ref_fields if row[name]]
    wanted.extend(link["subject_id"] for row_links in links.values() for link in row_links)
    infos = ref_infos(session, wanted) if wanted else {}
    items = []
    for row in rows:
        entity_id = row["id"]
        row_links = links.get(entity_id, [])
        refs = {name: infos[row[name]].as_dict() for name in needs.ref_fields if row[name] in infos}
        refs.update(
            (f"links.{link['subject_id']}", infos[link["subject_id"]].as_dict())
            for link in row_links
            if link["subject_id"] in infos
        )
        item: dict[str, Any] = {"id": entity_id, **{name: row[name] for name in needs.system}}
        item["fields"] = {field.name: api_value(field, row, row_links) for field in needs.fields}
        item["virtual"] = virtual.get(entity_id, {})
        if needs.derived:
            item["derived"] = derived_payload(derived.get(entity_id))
        item["refs"] = refs
        items.append(item)
    return items


def _vocabularies(spec: EntityTypeSpec, names: Sequence[str]) -> set[str]:
    return {
        field.vocabulary
        for field in (spec.field_map.get(name) for name in names)
        if field is not None and field.vocabulary
    }


# --------------------------------------------------------------------------------------
# Cell values
# --------------------------------------------------------------------------------------


def csv_cell(kind: ColumnKind, value: Any) -> str:
    """A CSV cell: booleans ``true``/``false``, numbers as numbers, and string cells
    starting with a formula character prefixed with an apostrophe."""
    if value is None:
        return ""
    if kind == "bool":
        return "true" if value else "false"
    if kind == "number":
        return format_number(value)
    text = str(value)
    if kind == "string" and text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def xlsx_text(text: str) -> str:
    """Replace characters that XLSX cannot hold with U+FFFD and truncate strings over
    32 767 characters (suffix `` [truncated]``)."""
    text = ILLEGAL_CHARACTERS_RE.sub("\ufffd", text)
    if len(text) > XLSX_MAX_CHARS:
        text = text[: XLSX_MAX_CHARS - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
    return text


def xlsx_cell(sheet: WriteOnlyWorksheet, kind: ColumnKind, value: Any) -> Cell | Any:
    """What to append for one cell: numbers and booleans as such, everything else as
    text that is stored as a string cell, never a formula or an error value.

    Text that openpyxl would store as a formula (``=…``) or an error value (``#N/A``)
    becomes an explicit cell with ``data_type = "s"``. Any other text is appended as a
    plain string, which openpyxl stores as a string cell as well, through one reused
    cell object: creating a cell per value made XLSX exports twice as slow.
    """
    if value is None:
        return None
    if kind == "bool":
        return bool(value)
    if kind == "number":
        return value
    text = xlsx_text(str(value))
    if text.startswith("=") or text in XLSX_ERROR_VALUES:
        cell = WriteOnlyCell(sheet, value=text)
        cell.data_type = "s"
        return cell
    return text


def export_filename(entity_type: str, file_format: str, now: datetime) -> str:
    """``<type>-<YYYYMMDD-HHMMSS>.<ext>`` in UTC (API §5)."""
    return f"{entity_type}-{now.astimezone(UTC):%Y%m%d-%H%M%S}.{file_format}"


# --------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------


class ExportJob:
    """A started export. It holds the export slot and its own read session (one
    snapshot for the count and every row) until the output is produced or
    :meth:`close` is called."""

    def __init__(
        self,
        session: Session,
        spec: EntityTypeSpec,
        selection: Selection | None,
        sort: Sequence[SortKey],
        columns: Sequence[Column],
        file_format: str,
        total: int,
        started_at: datetime,
        needs: ExportNeeds,
    ) -> None:
        self._session = session
        self.spec = spec
        self._selection = selection
        self._sort = tuple(sort)
        self.columns = tuple(columns)
        self._needs = needs
        self.format = file_format
        self.total = total
        self.filename = export_filename(spec.name, file_format, started_at)
        self.media_type = MEDIA_TYPES[file_format]
        self._closed = False
        self._used = False

    def close(self) -> None:
        """Release the session and the export slot (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            self._session.rollback()
            self._session.close()
        finally:
            _SLOT.release()

    def _start(self) -> None:
        if self._closed or self._used:
            raise RuntimeError("an export job produces its output only once")
        self._used = True

    def _value_rows(self) -> Iterator[list[list[Any]]]:
        """The column values of every row, in chunks; only what the columns read is
        loaded (:class:`ExportNeeds`)."""
        if self._selection is None:
            return
        for ids in iter_id_chunks(self._session, self._selection, self._sort, CHUNK_SIZE):
            items = export_items(self._session, self.spec, ids, self._needs)
            yield [[column.value(item) for column in self.columns] for item in items]

    def iter_csv(self) -> Iterator[bytes]:
        """Stream the CSV (UTF-8 with BOM, every cell quoted, header row)."""
        self._start()
        try:
            buffer = io.StringIO()
            writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
            writer.writerow([column.header for column in self.columns])
            yield ("\ufeff" + buffer.getvalue()).encode("utf-8")
            kinds = [column.kind for column in self.columns]
            for chunk in self._value_rows():
                buffer.seek(0)
                buffer.truncate()
                for values in chunk:
                    writer.writerow(
                        [csv_cell(kind, value) for kind, value in zip(kinds, values, strict=True)]
                    )
                yield buffer.getvalue().encode("utf-8")
        finally:
            self.close()

    def write_xlsx(self, target: str | Path | IO[bytes]) -> None:
        """Write the XLSX workbook: one sheet named after the type, bold frozen header."""
        self._start()
        try:
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet(title=self.spec.name)
            sheet.freeze_panes = "A2"
            header = []
            for column in self.columns:
                cell = WriteOnlyCell(sheet, value=column.header)
                cell.data_type = "s"
                cell.font = Font(bold=True)
                header.append(cell)
            sheet.append(header)
            kinds = [column.kind for column in self.columns]
            for chunk in self._value_rows():
                for values in chunk:
                    sheet.append(
                        [
                            xlsx_cell(sheet, kind, value)
                            for kind, value in zip(kinds, values, strict=True)
                        ]
                    )
            workbook.save(target)
        finally:
            self.close()


def _file_format(raw: str | None) -> str:
    value = raw or "csv"
    if value not in FORMATS:
        raise ValidationError.single("format", "must be csv or xlsx")
    return value


def start_export(session: Session, entity_type: str, params: QueryParams) -> ExportJob:
    """Validate an export request (filters, sort, ``cols``, ``format``) and start the job.

    Raises :class:`BusyError` while another export runs and
    :class:`ExportTooLargeError` over :data:`MAX_EXPORT_ROWS` rows. The job uses its own
    session on the same engine, so it may outlive the request's session.
    """
    spec = generic_spec(entity_type)
    pairs = param_pairs(params)
    file_format = _file_format(last_param(pairs, "format"))
    scope = parse_scope(spec, pairs)
    sort = parse_sort_param(spec, pairs, scope)
    names = column_names(spec, last_param(pairs, "cols"))
    if not _SLOT.acquire(blocking=False):
        raise BusyError()
    job_session = Session(bind=session.get_bind(), info=dict(session.info))
    try:
        labels = _Labels()
        labels.load(job_session, _vocabularies(spec, names))
        selection = select_scope(spec, scope)
        total = 0
        if selection is not None:
            total = int(job_session.execute(selection.count()).scalar_one())
        if total > MAX_EXPORT_ROWS:
            raise ExportTooLargeError(
                f"The export would have {total} rows; at most {MAX_EXPORT_ROWS} are allowed"
            )
        columns = build_columns(spec, names, labels)
        return ExportJob(
            job_session,
            spec,
            selection,
            sort,
            columns,
            file_format,
            total,
            datetime.now(UTC),
            export_needs(spec, names),
        )
    except BaseException:
        job_session.rollback()
        job_session.close()
        _SLOT.release()
        raise
