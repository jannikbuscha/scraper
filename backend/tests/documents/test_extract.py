"""Text extraction (documents/extract.py, docs/COLLECTORS.md §10.2)."""

from __future__ import annotations

import pytest

from mdt.collectors.parsing.texts import normalize_document_text
from mdt.collectors.store import DOCX, PDF, XLSX
from mdt.documents.extract import ExtractionError, extract_text, kind_of
from tests.documents.helpers import blank_pdf, docx_bytes, zip_bytes
from tests.parsing.helpers import fixture_bytes


def test_the_pdf_fixture_gives_its_text_layer() -> None:
    body = fixture_bytes("ministry_news", "storage_pdf_draft_resolution.pdf")
    extraction = extract_text(body, PDF)
    assert extraction.method == "pdf"
    assert extraction.text is not None
    lines = extraction.text.splitlines()
    # Lines read from the fixture's first page.
    assert "ПОСТАНОВА" in [line.strip() for line in lines]
    assert extraction.text == normalize_document_text(extraction.text)
    assert extraction.warnings == ()
    assert extraction.title is None  # the file has no metadata title


def test_a_pdf_without_text_layer_warns_and_keeps_its_metadata_title() -> None:
    extraction = extract_text(blank_pdf(title="Example scanned report"), PDF)
    assert (extraction.method, extraction.text) == ("pdf", None)
    assert extraction.title == "Example scanned report"
    assert [warning.code for warning in extraction.warnings] == ["no_text_layer"]


def test_an_unreadable_pdf_gives_no_text() -> None:
    extraction = extract_text(b"%PDF-1.7 broken", PDF)
    assert (extraction.method, extraction.text) == ("pdf", None)
    assert [warning.code for warning in extraction.warnings] == ["no_text"]


def test_docx_paragraphs_runs_tabs_and_breaks() -> None:
    body = docx_bytes(
        '<w:p><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        "<w:r><w:t>Example</w:t></w:r><w:r><w:tab/><w:t>heading</w:t></w:r></w:p>"
        "<w:p><w:r><w:t xml:space='preserve'>First line </w:t><w:br/><w:t>second line</w:t></w:r>"
        "<w:del><w:r><w:delText>deleted</w:delText></w:r></w:del></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:p><w:hyperlink><w:r><w:t>Linked text</w:t></w:r></w:hyperlink></w:p>",
        title="Example document title",
    )
    extraction = extract_text(body, DOCX)
    assert extraction.method == "docx"
    assert extraction.text == "Example\theading\nFirst line\nsecond line\nCell\nLinked text"
    assert extraction.title == "Example document title"


def test_a_docx_without_core_properties_has_no_title() -> None:
    extraction = extract_text(docx_bytes("<w:p><w:r><w:t>Text</w:t></w:r></w:p>"), DOCX)
    assert (extraction.text, extraction.title) == ("Text", None)


def test_a_broken_docx_gives_no_text() -> None:
    extraction = extract_text(zip_bytes(), DOCX)
    assert (extraction.method, extraction.text) == ("docx", None)
    assert [warning.code for warning in extraction.warnings] == ["no_text"]


def test_html_uses_the_generic_text_and_title() -> None:
    body = (
        b"<html><head><title>Example page</title><script>x()</script></head>"
        b"<body><h1>Example heading</h1><p>Body text</p><footer>Example footer</footer></body>"
        b"</html>"
    )
    extraction = extract_text(body, "text/html")
    assert extraction.method == "html"
    assert extraction.text == "Example heading\nBody text\nExample footer"
    assert extraction.title == "Example heading"


def test_html_decoding_warnings_are_passed_on() -> None:
    extraction = extract_text(b"<p>caf\xe9</p>", "text/html")
    assert [warning.code for warning in extraction.warnings] == ["invalid_value"]


def test_an_empty_html_body_gives_no_text() -> None:
    extraction = extract_text(b"<html><body><script>x()</script></body></html>", "text/html")
    assert extraction.text is None
    assert [warning.code for warning in extraction.warnings] == ["no_text"]


@pytest.mark.parametrize(
    "body",
    [
        "Приклад тексту\r\nдругий рядок".encode(),
        b"\xef\xbb\xbf" + "Приклад тексту\nдругий рядок".encode(),
        "Приклад тексту\nдругий рядок".encode("utf-16"),
    ],
)
def test_text_files_in_utf8_or_utf16_with_bom(body: bytes) -> None:
    extraction = extract_text(body, "text/plain")
    assert (extraction.method, extraction.text) == ("txt", "Приклад тексту\nдругий рядок")


def test_other_encodings_are_refused() -> None:
    with pytest.raises(ExtractionError, match="not UTF-8"):
        extract_text("Приклад".encode("cp1251"), "text/plain")
    with pytest.raises(ExtractionError, match="not UTF-8"):
        extract_text("Приклад".encode("cp1251"), "application/octet-stream", "notes.txt")


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [("image/png", "a.png"), (XLSX, "a.xlsx"), ("application/octet-stream", "a.zip"), (None, None)],
)
def test_other_types_are_stored_without_text(
    content_type: str | None, filename: str | None
) -> None:
    extraction = extract_text(b"\x89PNG\r\n", content_type, filename)
    assert (extraction.method, extraction.text, extraction.char_count) == ("none", None, 0)
    assert [warning.code for warning in extraction.warnings] == ["no_text"]


def test_kinds() -> None:
    assert kind_of(PDF) == "pdf"
    assert kind_of(DOCX) == "docx"
    assert kind_of("application/xhtml+xml") == "html"
    assert kind_of("text/csv") == "txt"
    assert kind_of("application/octet-stream", "NOTES.TXT") == "txt"
    assert kind_of("image/jpeg", "photo.txt") == "none"
