"""Page parsers of C4 ``ministry_news`` (docs/COLLECTORS.md §8.4, SOURCES S4): pure
functions of a stored snapshot (no network, no database, no clock).

* news: the listing pages (items with the values change detection compares) and the
  articles (dated by the Kyiv date of ``publishedAt.iso8601``; text = ``lead`` + ``blocks``);
* documents: the listing pages and the ``relatedDocuments`` of ``/ministry`` (one item per
  listed document, :func:`document_item`), ``content`` pages with their attachments, and
  storage files completed by their body (:func:`with_file`);
* the ``/ministry`` page and the year-in-review microsites.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import unquote, urlsplit

from mdt.collectors.base import Candidate, Snapshot
from mdt.collectors.mappings import LabelMapping
from mdt.collectors.parsing import ParseError, ParseResult
from mdt.collectors.parsing.html_text import read_page
from mdt.collectors.parsing.language import detect_language
from mdt.collectors.parsing.tiptap import tiptap_to_text
from mdt.collectors.store import DOCX, OCTET_STREAM, PDF
from mdt.collectors.thedigital import (
    NOT_FOUND_STATUSES,
    PUBLISHER,
    SITE,
    TURBO_STREAM,
    SiteValues,
    evidence_of,
    joined_text,
    last_segment,
    list_of,
    loader_entry,
    mapping_of,
    optional_text,
    page_licence,
    published_of,
    text_of,
)
from mdt.documents.extract import Extraction, ExtractionError, extract_text

NEWS_URL = f"{SITE}/news"
DOCUMENTS_URL = f"{SITE}/documents"
MINISTRY_URL = f"{SITE}/ministry"
STORAGE_HOST = "storage.thedigital.gov.ua"
#: A storage file: ``/files/<x>/<yx>/<32 hex = MD5 of the content>.<ext>``.
STORAGE_FILE = re.compile(r"^/files/(?:[^/]+/)*([0-9a-f]{32})\.[A-Za-z0-9]+$")
#: ``extraction_method`` of a listed reference without text.
LISTING_ONLY = "listing_only"
#: Licence of storage files (SOURCES §5 item 6) and of microsites without a statement.
UNKNOWN_LICENCE = "unknown"
STATED = "stated_in_source"
#: Observation detail of a file whose body was read (it is never fetched again).
FETCHED = "fetched"
FILE, CONTENT, LINK = "file", "content", "link"
#: Content types by file extension, for files served without a specific type.
_TYPES_BY_EXTENSION = {".pdf": PDF, ".docx": DOCX}


# --------------------------------------------------------------------------------------
# Keys and URLs
# --------------------------------------------------------------------------------------


def news_key(slug: str) -> str:
    """The key of an article: its slug without the rubric segment."""
    return f"news:{last_segment(slug)}"


def storage_md5(url: str) -> str | None:
    """The MD5 a storage file is named after, or None for any other URL."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != STORAGE_HOST:
        return None
    match = STORAGE_FILE.match(parts.path)
    return match.group(1) if match else None


# --------------------------------------------------------------------------------------
# News
# --------------------------------------------------------------------------------------


def parse_news_listing(snapshot: Snapshot) -> ParseResult:
    """A news listing page (loader entry with ``articles`` and ``pagination``): one item
    per article in listing order (a candidate without fields: key, URL, title and the
    details that change detection compares); ``total`` and ``last_page``."""
    data = loader_entry(snapshot, ("articles",), required=("pagination",))
    result = _paginated(data)
    for index, raw in enumerate(list_of(data["articles"], "articles")):
        item = mapping_of(raw, f"articles[{index}]")
        slug = text_of(item.get("slug"), f"articles[{index}].slug")
        title = text_of(item.get("title"), f"articles[{index}].title")
        published = mapping_of(item.get("publishedAt") or {}, f"articles[{index}].publishedAt")
        url = f"{NEWS_URL}/{slug.strip('/')}"
        result.candidates.append(
            Candidate(
                entity_type="document",
                key=news_key(slug),
                evidence=evidence_of(snapshot),
                label=title,
                url=url,
                details={
                    "title": title,
                    "published_at": optional_text(published.get("iso8601")),
                    "url": url,
                },
            )
        )
    return result


def _paginated(data: Mapping[str, Any]) -> ParseResult:
    pagination = mapping_of(data["pagination"], "pagination")
    facts = []
    for name in ("total", "lastPage"):
        value = pagination.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ParseError(f"pagination.{name} is not a count")
        facts.append(value)
    return ParseResult(total=facts[0], last_page=facts[1])


def parse_article(snapshot: Snapshot, values: SiteValues) -> ParseResult:
    """An article page (loader entry with ``article``): the article as a document. Its date
    is the Kyiv date of ``publishedAt.iso8601`` (``publishedAt.text`` and ``related`` are
    never read); its text the ``lead`` and the ``blocks``. A 404 or 410 is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    article = mapping_of(loader_entry(snapshot, ("article",))["article"], "article")
    article_id = text_of(article.get("id"), "article.id")
    title = text_of(article.get("title"), "article.title")
    slug = text_of(article.get("slug"), "article.slug")
    text = joined_text(
        tiptap_to_text(article.get("lead")).text, tiptap_to_text(article.get("blocks")).text
    )
    licence, warnings = page_licence(snapshot, values.default_licence)
    url = f"{NEWS_URL}/{slug.strip('/')}"
    fields: dict[str, Any] = {
        "doc_type": "news",
        "title": title,
        "url": url,
        "publisher": PUBLISHER,
        "language": detect_language(title, text),
        "license": licence,
    }
    if values.focal_org_id is not None:
        fields["publisher_org_id"] = values.focal_org_id
    published_at = mapping_of(article.get("publishedAt") or {}, "article.publishedAt")
    iso = optional_text(published_at.get("iso8601"))
    date = published_of(iso)
    if date is None or iso is None:
        warnings.append(("invalid_value", f"{url}: publishedAt.iso8601 is missing or invalid"))
    else:
        fields |= {
            "published": date.date,
            "published_basis": STATED,
            "published_text": iso,
            "published_at_utc": date.utc,
        }
    candidate = Candidate(
        entity_type="document",
        key=news_key(slug),
        evidence=evidence_of(snapshot),
        label=title,
        url=url,
        external_id=article_id,
        fields={name: value for name, value in fields.items() if value is not None},
        text=text,
        text_snapshot_id=snapshot.raw_snapshot_id,
        extraction_method=TURBO_STREAM,
    )
    return ParseResult(candidates=[candidate], warnings=warnings)


# --------------------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------------------


def parse_documents_listing(snapshot: Snapshot, kinds: LabelMapping) -> ParseResult:
    """A documents listing page (loader entry with ``documents`` and ``pagination``): one
    item per listed document in listing order (:func:`document_item`); ``total`` and
    ``last_page``."""
    data = loader_entry(snapshot, ("documents",), required=("pagination",))
    result = _paginated(data)
    for index, raw in enumerate(list_of(data["documents"], "documents")):
        item, warnings = document_item(mapping_of(raw, f"documents[{index}]"), snapshot, kinds)
        result.candidates.append(item)
        result.warnings.extend(warnings)
    return result


def document_item(
    item: Mapping[str, Any], snapshot: Snapshot, kinds: LabelMapping
) -> tuple[Candidate, list[tuple[str, str]]]:
    """One listed document (a documents listing or the ``relatedDocuments`` of a page) as
    a candidate from the listing alone, and the warnings of its kind:

    * ``file``: key ``file:<md5>`` (``doc:<group/slug>`` when the URL is no storage file),
      ``url`` = ``externalUrl``, ``license = unknown``; its text comes from the file;
    * ``content``: key ``doc:<group/slug>``, ``url`` = the document's page;
    * ``link``: key ``doc:<group/slug>``, ``url`` = ``externalUrl``, no text
      (``extraction_method = listing_only``, the text version names the listing page).

    ``doc_type`` comes from the kind (``ministry_document_kinds``), ``source_record_at``
    from ``publishedAt.iso8601`` (the site's record date, never ``published``). The
    details are the listing values that change detection compares."""
    kind = item.get("type")
    slug = text_of(item.get("slug"), "document slug").strip("/")
    title = text_of(item.get("title"), f"title of {slug}")
    kind_slug = optional_text(mapping_of(item.get("kind") or {}, f"kind of {slug}").get("slug"))
    published = mapping_of(item.get("publishedAt") or {}, f"publishedAt of {slug}")
    iso = optional_text(published.get("iso8601"))
    warnings: list[tuple[str, str]] = []
    fields: dict[str, Any] = {"title": title}
    doc_type = _doc_type(kinds, kind_slug, slug, warnings)
    if doc_type is not None:
        fields["doc_type"] = doc_type
    record = published_of(iso)
    if record is not None:
        fields["source_record_at"] = record.utc
    key = f"doc:{slug}"
    candidate_args: dict[str, Any] = {}
    if kind == FILE:
        url = text_of(item.get("externalUrl"), f"externalUrl of {slug}")
        md5 = storage_md5(url)
        key = f"file:{md5}" if md5 else key
        fields["license"] = UNKNOWN_LICENCE
    elif kind == CONTENT:
        url = f"{DOCUMENTS_URL}/{slug}"
    elif kind == LINK:
        url = text_of(item.get("externalUrl"), f"externalUrl of {slug}")
        candidate_args = {
            "extraction_method": LISTING_ONLY,
            "text_snapshot_id": snapshot.raw_snapshot_id,
        }
    else:
        raise ParseError(f"the type of {slug} is neither {FILE}, {CONTENT} nor {LINK}")
    fields["url"] = url
    candidate = Candidate(
        entity_type="document",
        key=key,
        evidence=evidence_of(snapshot),
        label=title,
        url=url,
        fields=fields,
        details={"type": kind, "kind": kind_slug, "title": title, "published_at": iso, "url": url},
        **candidate_args,
    )
    return candidate, warnings


def _doc_type(
    kinds: LabelMapping, kind_slug: str | None, slug: str, warnings: list[tuple[str, str]]
) -> str | None:
    """The ``doc_type`` of a kind; an unmapped kind gives the fallback and a warning."""
    if kind_slug is None:
        return None
    found = kinds.lookup(kind_slug)
    if found.status in ("fallback", "unmapped"):
        warnings.append(
            (
                "unmapped_label",
                f"{slug}: the document kind {kind_slug!r} has no mapping in "
                f"{kinds.name}; {found.code or 'no code'} was used",
            )
        )
    return found.code


def parse_document_page(snapshot: Snapshot, kinds: LabelMapping, values: SiteValues) -> ParseResult:
    """A ``content`` document's page (loader entry with ``document``): the document (text
    from ``blocks``, licence by footer) followed by one file document per attachment (a
    link to a storage file; title = the link text, ``doc_type`` of the page). A 404 or 410
    is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    document = mapping_of(loader_entry(snapshot, ("document",))["document"], "document")
    document_id = text_of(document.get("id"), "document.id")
    slug = text_of(document.get("slug"), "document.slug").strip("/")
    title = text_of(document.get("title"), "document.title")
    kind_slug = optional_text(mapping_of(document.get("kind") or {}, "document.kind").get("slug"))
    published = mapping_of(document.get("publishedAt") or {}, "document.publishedAt")
    body = tiptap_to_text(document.get("blocks"))
    licence, warnings = page_licence(snapshot, values.default_licence)
    doc_type = _doc_type(kinds, kind_slug, slug, warnings)
    record = published_of(published.get("iso8601"))
    url = f"{DOCUMENTS_URL}/{slug}"
    fields: dict[str, Any] = {
        "title": title,
        "url": url,
        "doc_type": doc_type,
        "publisher": PUBLISHER,
        "language": detect_language(title, body.text),
        "source_record_at": record.utc if record else None,
        "license": licence,
    }
    evidence = evidence_of(snapshot)
    result = ParseResult(warnings=warnings)
    result.candidates.append(
        Candidate(
            entity_type="document",
            key=f"doc:{slug}",
            evidence=evidence,
            label=title,
            url=url,
            external_id=document_id,
            fields={name: value for name, value in fields.items() if value is not None},
            text=body.text or None,
            text_snapshot_id=snapshot.raw_snapshot_id,
            extraction_method=TURBO_STREAM,
        )
    )
    keys: set[str] = set()
    for link in body.links:
        md5 = storage_md5(link.href)
        if md5 is None or f"file:{md5}" in keys:
            continue
        keys.add(f"file:{md5}")
        attachment = {"title": link.text, "url": link.href, "license": UNKNOWN_LICENCE}
        if doc_type is not None:
            attachment["doc_type"] = doc_type
        result.candidates.append(
            Candidate(
                entity_type="document",
                key=f"file:{md5}",
                evidence=evidence,
                label=link.text or None,
                url=link.href,
                fields={name: value for name, value in attachment.items() if value},
                details={"type": FILE, "kind": kind_slug, "title": link.text, "url": link.href},
            )
        )
    return result


def with_file(item: Candidate, snapshot: Snapshot) -> tuple[Candidate, list[tuple[str, str]]]:
    """A file document completed by its stored body: the text extracted by type (PDF,
    DOCX; other types give no text, ``extraction_method = none``), the language of the
    text, and the detail that the file was read. A storage file whose body does not have
    the MD5 of its name gives ``checksum_mismatch`` (the body is kept)."""
    warnings: list[tuple[str, str]] = []
    name = unquote(urlsplit(item.url or "").path.rsplit("/", 1)[-1])
    expected = storage_md5(item.url or "")
    actual = hashlib.md5(snapshot.body, usedforsecurity=False).hexdigest()
    if expected is not None and actual != expected:
        warnings.append(
            ("checksum_mismatch", f"{item.url}: the body's MD5 is {actual}, not {expected}")
        )
    extraction = _extract(snapshot, name)
    fields = dict(item.fields)
    snapshots = dict(item.field_snapshots)
    title = str(fields.get("title") or "")
    if extraction.text is not None:
        language = detect_language(title, extraction.text)
        if language is not None:
            fields["language"] = language
            snapshots["language"] = [snapshot.raw_snapshot_id]
    candidate = replace(
        item,
        fields=fields,
        field_snapshots=snapshots,
        text=extraction.text,
        text_snapshot_id=snapshot.raw_snapshot_id,
        extraction_method=extraction.method,
        details={**item.details, FETCHED: True},
    )
    return candidate, warnings


def _extract(snapshot: Snapshot, name: str) -> Extraction:
    content_type = snapshot.content_type
    if content_type in (None, OCTET_STREAM):
        extension = name[name.rfind(".") :].lower() if "." in name else ""
        content_type = _TYPES_BY_EXTENSION.get(extension, content_type)
    try:
        return extract_text(snapshot.body, content_type, name)
    except ExtractionError:
        return Extraction("none", None)


# --------------------------------------------------------------------------------------
# /ministry and the microsites
# --------------------------------------------------------------------------------------


def parse_ministry_page(snapshot: Snapshot, kinds: LabelMapping, values: SiteValues) -> ParseResult:
    """The ``/ministry`` page (loader entry with ``page``): the page as a document
    (``doc_type = other``; title and text by docs/COLLECTORS.md §7.3, so without team
    members and embedded documents), followed by its embedded document items
    (``relatedDocuments``, the shape of listing items, :func:`document_item`). A 404 or
    410 is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    page = mapping_of(loader_entry(snapshot, ("page",))["page"], "page")
    page_id = text_of(page.get("id"), "page.id")
    title = text_of(page.get("title"), "page.title")
    slug = text_of(page.get("slug"), "page.slug").strip("/")
    body = tiptap_to_text(page.get("blocks"))
    licence, warnings = page_licence(snapshot, values.default_licence)
    url = f"{SITE}/{slug}"
    fields: dict[str, Any] = {
        "doc_type": "other",
        "title": title,
        "url": url,
        "publisher": PUBLISHER,
        "language": detect_language(title, body.text),
        "license": licence,
    }
    result = ParseResult(warnings=warnings)
    result.candidates.append(
        Candidate(
            entity_type="document",
            key=f"page:{slug}",
            evidence=evidence_of(snapshot),
            label=title,
            url=url,
            external_id=page_id,
            fields={name: value for name, value in fields.items() if value is not None},
            text=body.text or None,
            text_snapshot_id=snapshot.raw_snapshot_id,
            extraction_method=TURBO_STREAM,
        )
    )
    for index, raw in enumerate(_related_documents(page.get("blocks"))):
        item, item_warnings = document_item(
            mapping_of(raw, f"relatedDocuments[{index}]"), snapshot, kinds
        )
        result.candidates.append(item)
        result.warnings.extend(item_warnings)
    return result


def _related_documents(node: Any) -> list[Any]:
    """The items of every ``relatedDocuments`` node, depth-first in document order."""
    if isinstance(node, list):
        return [item for child in node for item in _related_documents(child)]
    if not isinstance(node, dict):
        return []
    if node.get("type") == "relatedDocuments":
        attrs = mapping_of(node.get("attrs") or {}, "relatedDocuments.attrs")
        return list_of(attrs.get("documents") or [], "relatedDocuments.documents")
    return _related_documents(node.get("content"))


def parse_microsite(snapshot: Snapshot) -> ParseResult:
    """A year-in-review microsite: one document (key ``microsite:<requested host>``,
    ``doc_type = report``, ``url`` and ``publisher`` from the final URL, text by
    docs/COLLECTORS.md §7.4, licence by its statement, else ``unknown``; no date). A 404 or
    410 is ``not_found``."""
    if snapshot.http_status in NOT_FOUND_STATUSES:
        return ParseResult(not_found=True)
    page = read_page(snapshot)
    if page.title is None:
        raise ParseError("the page has no title")
    url = snapshot.final_url or snapshot.url or ""
    host = (urlsplit(snapshot.url or url).hostname or "").lower()
    fields: dict[str, Any] = {
        "doc_type": "report",
        "title": page.title,
        "url": url,
        "publisher": (urlsplit(url).hostname or "").lower(),
        "language": detect_language(page.title, page.text),
        "license": page.licence or UNKNOWN_LICENCE,
    }
    candidate = Candidate(
        entity_type="document",
        key=f"microsite:{host}",
        evidence=evidence_of(snapshot),
        label=page.title,
        url=url,
        fields={name: value for name, value in fields.items() if value is not None},
        text=page.text or None,
        text_snapshot_id=snapshot.raw_snapshot_id,
        extraction_method="html",
    )
    return ParseResult(candidates=[candidate], warnings=list(page.warnings))
