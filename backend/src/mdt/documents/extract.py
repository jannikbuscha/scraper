"""Text extraction from PDF, DOCX, HTML and TXT (docs/COLLECTORS.md §10.2; shared with the
C4 file documents).

* PDF (``pdf``): the pypdf text layer, pages joined with a blank line. There is no OCR, so a
  PDF without a text layer gets no text and the warning ``no_text_layer``.
* DOCX (``docx``): ``word/document.xml`` read with ``zipfile`` and ElementTree: paragraphs
  as lines, runs (``w:t``), ``w:tab`` as a tab, ``w:br`` as a line break.
* HTML (``html``): the generic text of docs/COLLECTORS.md §7.4.
* TXT (``txt``): UTF-8 with or without BOM, or UTF-16 with BOM; anything else raises
  :class:`ExtractionError`.

Other types (images, XLSX, ZIP, …) give no text (``none``, warning ``no_text``). Texts are
normalised as document texts (docs/DATA_MODEL.md §15.6). Titles come from the HTML title
or the PDF or DOCX metadata title.
"""

from __future__ import annotations

import codecs
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from mdt.collectors.parsing.html_text import (
    body_of,
    decode_html,
    html_text,
    page_title,
    parse_html,
    remove_hidden,
)
from mdt.collectors.parsing.texts import collapse_whitespace, normalize_document_text
from mdt.collectors.store import DOCX, PDF

log = logging.getLogger("mdt.documents")

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_TYPES = frozenset({"text/plain", "text/csv"})
#: File name extensions read as text when the content type says nothing more specific.
TEXT_EXTENSIONS = frozenset({".txt", ".text", ".csv"})
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"


class ExtractionError(ValueError):
    """The file cannot be read as its type requires (a text file that is not UTF-8)."""


@dataclass(frozen=True)
class ExtractionWarning:
    """A warning of the extraction (``code`` as in docs/API.md §7.8, plain message)."""

    code: str
    message: str


@dataclass(frozen=True)
class Extraction:
    """The text of a file: method, normalised text (None without text), metadata title and
    warnings."""

    method: str
    text: str | None
    title: str | None = None
    warnings: tuple[ExtractionWarning, ...] = ()

    @property
    def char_count(self) -> int:
        """Characters of the text (0 without text)."""
        return len(self.text or "")


def kind_of(content_type: str | None, filename: str | None = None) -> str:
    """``pdf``, ``docx``, ``html``, ``txt`` or ``none`` for a content type (a text file with
    an undetected encoding counts as ``txt`` by its extension, so it is refused with a clear
    message instead of being stored without text)."""
    if content_type == PDF:
        return "pdf"
    if content_type == DOCX:
        return "docx"
    if content_type in HTML_TYPES:
        return "html"
    if content_type in TEXT_TYPES:
        return "txt"
    unspecific = content_type in (None, "application/octet-stream")
    if unspecific and filename and PurePosixPath(filename).suffix.lower() in TEXT_EXTENSIONS:
        return "txt"
    return "none"


def extract_text(body: bytes, content_type: str | None, filename: str | None = None) -> Extraction:
    """Extract the text of a stored body by its content type (docs/COLLECTORS.md §10.2)."""
    kind = kind_of(content_type, filename)
    if kind == "pdf":
        return _pdf(body)
    if kind == "docx":
        return _docx(body)
    if kind == "html":
        return _html(body, content_type)
    if kind == "txt":
        return _finish("txt", decode_text_file(body))
    return Extraction(
        "none",
        None,
        warnings=(ExtractionWarning("no_text", "no text is extracted from this type of file"),),
    )


def _finish(method: str, raw: str, title: str | None = None) -> Extraction:
    text = normalize_document_text(raw)
    if not text:
        return Extraction(
            method, None, title, (ExtractionWarning("no_text", "the file contains no text"),)
        )
    return Extraction(method, text, title)


def decode_text_file(body: bytes) -> str:
    """A text file: UTF-8 with or without BOM, or UTF-16 with BOM."""
    if body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return body.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise ExtractionError("the text file is not valid UTF-16") from exc
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError("the text file is not UTF-8") from exc


def _pdf(body: bytes) -> Extraction:
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
        metadata = reader.metadata
        title = collapse_whitespace(metadata.title) if metadata and metadata.title else None
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        log.info("PDF text extraction failed: %s", type(exc).__name__)
        return Extraction(
            "pdf", None, None, (ExtractionWarning("no_text", "the PDF could not be read"),)
        )
    text = normalize_document_text("\n\n".join(page.strip() for page in pages))
    if not text:
        warning = ExtractionWarning("no_text_layer", "the PDF has no text layer (no OCR is done)")
        return Extraction("pdf", None, title or None, (warning,))
    return Extraction("pdf", text, title or None)


def _docx(body: bytes) -> Extraction:
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            names = set(archive.namelist())
            core = (
                ET.fromstring(archive.read("docProps/core.xml"))
                if "docProps/core.xml" in names
                else None
            )
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        log.info("DOCX text extraction failed: %s", type(exc).__name__)
        return Extraction(
            "docx", None, None, (ExtractionWarning("no_text", "the DOCX file could not be read"),)
        )
    parts: list[str] = []
    _docx_walk(document, parts)
    title_element = core.find(_DC_TITLE) if core is not None else None
    title = collapse_whitespace(title_element.text or "") if title_element is not None else ""
    return _finish("docx", "".join(parts), title or None)


def _docx_walk(element: ET.Element, parts: list[str]) -> None:
    """Paragraphs as lines; within runs: text, tabs and breaks (deleted text and property
    elements give nothing)."""
    for child in element:
        tag = child.tag
        if tag == f"{_W}p":
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            _docx_walk(child, parts)
            parts.append("\n")
        elif tag == f"{_W}r":
            _docx_run(child, parts)
        elif tag not in (f"{_W}pPr", f"{_W}rPr", f"{_W}del"):
            _docx_walk(child, parts)


def _docx_run(run: ET.Element, parts: list[str]) -> None:
    for child in run:
        tag = child.tag
        if tag == f"{_W}t":
            parts.append(child.text or "")
        elif tag == f"{_W}tab":
            parts.append("\t")
        elif tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
        elif tag not in (f"{_W}rPr", f"{_W}delText", f"{_W}instrText"):
            _docx_walk(child, parts)


def _html(body: bytes, content_type: str | None) -> Extraction:
    decoded = decode_html(body, content_type)
    soup = parse_html(decoded.text)
    remove_hidden(soup)
    title = page_title(soup)
    extraction = _finish("html", html_text(body_of(soup)), title)
    warnings = tuple(ExtractionWarning(code, message) for code, message in decoded.warnings)
    return Extraction(extraction.method, extraction.text, title, warnings + extraction.warnings)
