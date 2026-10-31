"""Synthetic files for the document tests (no file contains real data)."""

from __future__ import annotations

import io
import zipfile

from pypdf import PdfWriter

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_bytes(paragraphs_xml: str, title: str | None = None) -> bytes:
    """A minimal DOCX whose body holds ``paragraphs_xml`` (``w:`` prefixed elements)."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W}">'
        f"<w:body>{paragraphs_xml}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        if title is not None:
            archive.writestr(
                "docProps/core.xml",
                '<?xml version="1.0"?><cp:coreProperties '
                'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
                ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f"<dc:title>{title}</dc:title></cp:coreProperties>",
            )
    return buffer.getvalue()


def blank_pdf(title: str | None = None) -> bytes:
    """A one-page PDF without a text layer (optionally with a metadata title)."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if title is not None:
        writer.add_metadata({"/Title": title})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def zip_bytes() -> bytes:
    """A ZIP archive that is neither DOCX nor XLSX."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "Example")
    return buffer.getvalue()
