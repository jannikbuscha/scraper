"""Reading CSV and XLSX uploads and checking mappings (importers/files.py, mapping.py;
docs/COLLECTORS.md §9.2, §9.3). All files and values are synthetic."""

from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl
import pytest

from mdt.collectors.store import SnapshotStore
from mdt.domain.errors import ValidationError
from mdt.domain.normalize import ValueProblem
from mdt.domain.registry import ENTITY_TYPES
from mdt.importers.files import (
    cell_text,
    column_names,
    detect_delimiter,
    read_csv,
    read_table,
    read_xlsx,
)
from mdt.importers.mapping import (
    CellParser,
    check_mapping,
    importable_fields,
    key_fields,
    suggest_mapping,
    table_spec,
)
from tests.conftest import Db
from tests.helpers import create_project


def xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    """A workbook with the given sheets and rows."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        worksheet = workbook.create_sheet(name)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _errors(exc: pytest.ExceptionInfo[ValidationError]) -> dict[str, list[str]]:
    return dict(exc.value.details or {})


# CSV -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "delimiter"),
    [("a,b;c", ","), ("a;b;c", ";"), ("a\tb\tc,d", "\t"), ("single", ","), ("a;b,c", ",")],
)
def test_the_delimiter_occurs_most_often_in_the_header(header: str, delimiter: str) -> None:
    # On a tie the order ",", ";", tab decides.
    assert detect_delimiter(header) == delimiter


def test_csv_with_bom_quoting_empty_rows_and_row_numbers() -> None:
    body = ('﻿slug;notes\nexample-a;"Line one\nline two; with ""quotes"""\n;\nexample-b;\n').encode()
    table = read_csv(body)
    assert table.columns == ("slug", "notes")
    assert table.rows == (
        (2, ("example-a", 'Line one\nline two; with "quotes"')),
        (4, ("example-b", "")),
    )
    assert table.sheets is None


def test_csv_must_be_utf8() -> None:
    with pytest.raises(ValidationError) as error:
        read_csv("slug\nприклад".encode("cp1251"))
    assert _errors(error) == {"upload_id": ["the CSV file is not UTF-8; save the file as UTF-8"]}
    with pytest.raises(ValidationError):
        read_csv("slug\nexample".encode("utf-16"))


def test_header_names() -> None:
    assert column_names([" slug ", "", "Notes", " "]) == ("slug", "column_2", "Notes", "column_4")
    with pytest.raises(ValidationError) as error:
        column_names(["slug", "slug "])
    assert "duplicate column headers: slug" in _errors(error)["upload_id"][0]


@pytest.mark.parametrize("body", [b"", b"\n", b" , \nexample,x"])
def test_a_file_without_header_cells_has_no_header(body: bytes) -> None:
    with pytest.raises(ValidationError) as error:
        read_csv(body)
    assert _errors(error) == {"upload_id": ["the file has no header row"]}


# XLSX ----------------------------------------------------------------------------------


def test_cell_texts() -> None:
    assert cell_text(None) == ""
    assert cell_text(True) == "true"
    assert cell_text(3) == "3"
    assert cell_text(3.0) == "3"
    assert cell_text(0.1) == "0.1"
    assert cell_text(1e-7) == "0.0000001"
    assert cell_text(datetime(2024, 5, 1)) == "2024-05-01"
    assert cell_text(datetime(2024, 5, 1, 10, 30)) == "2024-05-01T10:30:00"
    assert cell_text(date(2024, 5, 1)) == "2024-05-01"
    assert cell_text(" text ") == " text "


def test_xlsx_sheets_values_and_empty_rows() -> None:
    body = xlsx_bytes(
        {
            "First": [["slug", "count", None], ["example-a", 2.0, None], [None, None, None]],
            "Second": [["slug", "when"], ["example-b", datetime(2024, 5, 1)], ["example-c", 1.5]],
        }
    )
    first = read_xlsx(body, None)
    assert first.sheets == ("First", "Second") and first.sheet == "First"
    assert first.columns == ("slug", "count", "column_3")
    assert first.rows == ((2, ("example-a", "2", "")),)
    second = read_xlsx(body, "Second")
    assert second.rows == ((2, ("example-b", "2024-05-01")), (3, ("example-c", "1.5")))
    with pytest.raises(ValidationError) as error:
        read_xlsx(body, "Third")
    assert _errors(error) == {"sheet": ["the workbook has no sheet of this name"]}


def test_a_broken_xlsx_is_refused() -> None:
    with pytest.raises(ValidationError) as error:
        read_xlsx(b"PK\x03\x04 not a workbook", None)
    assert _errors(error) == {"upload_id": ["the XLSX file cannot be read"]}


def test_uploads_must_be_csv_or_xlsx(db: Db) -> None:
    store = SnapshotStore(db.settings.raw_path)
    with db.session() as session:
        csv_record = store.put_upload(session, [b"slug\nexample"], "data.csv")
        xlsx_record = store.put_upload(session, [xlsx_bytes({"S": [["slug"]]})], "data.xlsx")
        pdf_record = store.put_upload(session, [b"%PDF-1.4"], "data.pdf")
        latin = store.put_upload(session, ["slug\nприклад".encode("cp1251")], "data.csv")
    assert read_table(csv_record, b"slug\nexample", None).columns == ("slug",)
    with pytest.raises(ValidationError) as error:
        read_table(csv_record, b"slug\nexample", "Sheet1")
    assert _errors(error) == {"sheet": ["a CSV file has no sheets"]}
    assert read_table(xlsx_record, xlsx_bytes({"S": [["slug"]]}), None).sheet == "S"
    with pytest.raises(ValidationError) as error:
        read_table(pdf_record, b"%PDF-1.4", None)
    assert _errors(error) == {"upload_id": ["upload a CSV or XLSX file"]}
    with pytest.raises(ValidationError) as error:
        read_table(latin, b"", None)
    assert "save the file as UTF-8" in _errors(error)["upload_id"][0]


# Fields and mappings -------------------------------------------------------------------


def test_importable_and_key_fields() -> None:
    project = importable_fields("project")
    assert "slug" in project and "in_paper_scope" in project and "notes" in project
    for name in ("seed_key", "launch", "open_comments", "created_at", "version"):
        assert name not in project
    document = importable_fields("document")
    assert "links" not in document and "canonical_url" not in document
    assert "text_hash" not in document and "text" not in document
    assert key_fields("project") == ["id", "slug"]
    assert key_fields("document") == ["id", "url"]
    assert key_fields("event") == ["id"]
    with pytest.raises(ValidationError):
        table_spec("evidence")


def test_suggested_mapping_by_name_or_label() -> None:
    columns = ["ID", "Slug", "name (english)", "Notes", "slug", "unknown"]
    assert suggest_mapping("project", columns) == {
        "ID": "id",
        "Slug": "slug",
        "name (english)": "name_en",
        "Notes": "notes",
    }


def test_mapping_validation() -> None:
    columns = ("slug", "Name", "notes")
    assert check_mapping("project", columns, {"slug": "slug"}, "slug") == {"slug": "slug"}
    with pytest.raises(ValidationError) as error:
        check_mapping(
            "project",
            columns,
            {"slug": "slug", "Name": "seed_key", "notes": "slug", "missing": "notes"},
            "url",
        )
    assert set(_errors(error)) == {"mapping.Name", "mapping.notes", "mapping.missing", "key_field"}
    with pytest.raises(ValidationError) as error:
        check_mapping("project", columns, {"Name": "name_en"}, "slug")
    assert _errors(error) == {"key_field": ["map a column to slug to use it as the key"]}
    with pytest.raises(ValidationError):
        check_mapping("project", columns, ["slug"], None)


# Cells ---------------------------------------------------------------------------------


def test_cell_values_per_field_type(db: Db) -> None:
    project_spec = ENTITY_TYPES["project"]
    document_spec = ENTITY_TYPES["document"]
    service_spec = ENTITY_TYPES["service"]
    with db.session() as session:
        project = create_project(session, slug="example-ref")
        parser = CellParser(session)
        field = project_spec.field
        assert parser.parse(field("status"), " active ") == "active"
        assert parser.parse(field("paper_cluster"), "example CLUSTER_B") == "cluster_b"
        assert parser.parse(field("paper_cluster"), "Cluster_A") == "cluster_a"
        assert parser.parse(field("paper_cluster"), "nothing") == "nothing"
        assert parser.parse(field("ministry_categories"), "category_a; Example category_b;") == [
            "category_a",
            "category_b",
        ]
        assert parser.parse(
            field("official_urls"), "https://example.org/a;https://example.org/b"
        ) == [
            "https://example.org/a",
            "https://example.org/b",
        ]
        assert parser.parse(field("aliases"), "Example; EX") == [
            {"text": "Example"},
            {"text": "EX"},
        ]
        for text, value in (
            ("TRUE", True),
            ("yes", True),
            ("1", True),
            ("No", False),
            ("0", False),
        ):
            assert parser.parse(field("in_paper_scope"), text) is value
        with pytest.raises(ValueProblem):
            parser.parse(field("in_paper_scope"), "maybe")
        assert parser.parse(service_spec.field("project_id"), "example-ref") == project.entity_id
        assert (
            parser.parse(service_spec.field("project_id"), project.entity_id) == project.entity_id
        )
        assert parser.parse(service_spec.field("project_id"), "no-such-slug") == "no-such-slug"
        assert parser.parse(document_spec.field("published"), "2024-05") == "2024-05"
        indicator = ENTITY_TYPES["indicator"]
        assert parser.parse(indicator.field("value"), "-1.25") == -1.25
        with pytest.raises(ValueProblem):
            parser.parse(indicator.field("value"), "1,25")
        participation = ENTITY_TYPES["evidence"]
        assert parser.parse(participation.field("char_start"), "12") == 12
        with pytest.raises(ValueProblem):
            parser.parse(participation.field("char_start"), "1.5")
