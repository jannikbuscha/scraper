# ruff: noqa: RUF001
"""HTML to text, titles, licence phrases, links and client-rendered shells
(docs/COLLECTORS.md §7.1, §7.4, §8.2, §4.1).

* **Decoding:** a byte order mark, else the charset of ``Content-Type``, else
  ``<meta charset>``, else UTF-8; undecodable bytes are replaced and give the warning
  ``invalid_value``. HTML is parsed with BeautifulSoup and Python's ``html.parser`` (the
  fixture excerpts were serialised with it).
* **Hidden content** is removed before any text is read: ``script``, ``style``,
  ``noscript``, ``template``, ``svg``, ``iframe``, form controls, and elements with
  ``hidden`` or ``aria-hidden="true"``.
* **Generic text:** the whole ``body`` (footer statements on operator, owner and licence
  stay), with line breaks after block elements (a block element also starts a new line, so
  text before it does not run into its first word; table cells are separated by a space),
  whitespace collapsed within lines and empty lines dropped, then the document text
  normalisation (docs/DATA_MODEL.md §15.6). Collectors with selectors (C3, C4b) extract
  their own parts from :attr:`HtmlPage.soup`.
* **Title:** the first ``h1``, else ``<title>``.
* **Licence phrases:** the CC BY 4.0 sentences of thedigital.gov.ua and www.kmu.gov.ua give
  ``cc_by_4_0``, the "all rights reserved" phrases ``all_rights_reserved``; otherwise
  None, and the collector uses its default from ``sources.yaml``.
* **Client-rendered shell** (C2): an application root (an ``<app-root>`` element or an
  ``ng-version`` attribute) with less than 200 characters of visible body text.
* **Links:** absolute http(s) URLs; hidden trap links (``rel=nofollow`` together with
  ``aria-hidden``) and ``/cdn-cgi/`` paths are dropped (SOURCES §2).
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString, Script, Stylesheet, Tag, TemplateString

from mdt.collectors.base import Snapshot
from mdt.collectors.parsing.texts import collapse_whitespace, normalize_document_text
from mdt.collectors.parsing.tiptap import outbound_href
from mdt.domain.text import fold

#: Removed before reading text (docs/COLLECTORS.md §7.4).
REMOVED_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "input",
    "button",
    "select",
    "option",
    "optgroup",
    "textarea",
    "datalist",
)
#: Elements followed by a line break.
BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "br",
        "table",
    }
)
#: The CC BY 4.0 statements of thedigital.gov.ua (SOURCES S1) and www.kmu.gov.ua (S4b).
CC_BY_PHRASES = (
    "Весь контент доступний за ліцензією Creative Commons Attribution 4.0 International "
    "license, якщо не зазначено інше",
    "All content is available under the Creative Commons Attribution 4.0 International "
    "license unless otherwise noted",
)
ALL_RIGHTS_RESERVED_PHRASES = (
    "Всі права захищені",
    "Усі права захищено",
    "Усі права захищені",
    "All rights reserved",
)
#: Table cells: followed by a space, so that the words of adjacent cells stay apart.
CELL_TAGS = frozenset({"td", "th"})
CLIENT_SHELL_MAX_CHARS = 200
TRAP_PATH_PREFIX = "/cdn-cgi/"

_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE
)
_SKIPPED_STRINGS = (PreformattedString, Script, Stylesheet, TemplateString)
_BOMS = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


@dataclass(frozen=True)
class DecodedHtml:
    """A decoded body and the warnings of decoding (``(code, message)`` pairs)."""

    text: str
    warnings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PageLink:
    """A link of a page: an absolute http(s) URL and its collapsed text."""

    href: str
    text: str


@dataclass(frozen=True)
class HtmlPage:
    """A parsed page with hidden content removed, and what every collector reads."""

    soup: BeautifulSoup
    text: str
    title: str | None
    licence: str | None
    client_shell: bool
    warnings: tuple[tuple[str, str], ...]


def charset_of(content_type: str | None) -> str | None:
    """The ``charset`` parameter of a ``Content-Type`` value."""
    for part in (content_type or "").split(";")[1:]:
        name, _, value = part.partition("=")
        if name.strip().lower() == "charset" and value.strip().strip("\"'"):
            return value.strip().strip("\"'")
    return None


def decode_html(body: bytes, content_type: str | None = None) -> DecodedHtml:
    """Decode an HTML body: byte order mark, ``Content-Type`` charset, ``<meta charset>``,
    else UTF-8 (docs/COLLECTORS.md §7.1)."""
    for bom, encoding in _BOMS:
        if body.startswith(bom):
            return _decode(body[len(bom) :], encoding, "byte order mark")
    declared = charset_of(content_type)
    if declared:
        return _decode(body, declared, "Content-Type")
    match = _META_CHARSET.search(body[:4096])
    if match:
        return _decode(body, match.group(1).decode("ascii"), "meta charset")
    return _decode(body, "utf-8", "default")


def _decode(body: bytes, encoding: str, basis: str) -> DecodedHtml:
    warnings: list[tuple[str, str]] = []
    try:
        codecs.lookup(encoding)
    except LookupError:
        warnings.append(("invalid_value", f"unknown charset from {basis}; decoded as UTF-8"))
        encoding = "utf-8"
    try:
        return DecodedHtml(body.decode(encoding), tuple(warnings))
    except UnicodeDecodeError:
        warnings.append(("invalid_value", f"undecodable bytes in a {encoding} body were replaced"))
        return DecodedHtml(body.decode(encoding, errors="replace"), tuple(warnings))


def parse_html(text: str) -> BeautifulSoup:
    """Parse with Python's built-in ``html.parser``."""
    return BeautifulSoup(text, "html.parser")


def _is_hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden"):
        return True
    value = tag.get("aria-hidden")
    return isinstance(value, str) and value.strip().lower() == "true"


def remove_hidden(root: Tag) -> None:
    """Remove the elements of :data:`REMOVED_TAGS` and hidden elements, in place."""
    for tag in root.find_all(REMOVED_TAGS):
        tag.decompose()
    for tag in root.find_all(_is_hidden):
        if not tag.decomposed:
            tag.decompose()


def html_text(root: Tag) -> str:
    """The text of ``root`` (normally the cleaned ``body``): one line per block, whitespace
    collapsed within lines, empty lines dropped, normalised (DATA_MODEL §15.6).
    ``<title>`` elements give no text."""
    parts: list[str] = []
    _collect(root, parts)
    lines = (collapse_whitespace(line) for line in "".join(parts).split("\n"))
    return normalize_document_text("\n".join(line for line in lines if line))


def _collect(node: Tag, parts: list[str]) -> None:
    for child in node.children:
        if isinstance(child, Tag):
            if child.name == "title":
                continue
            block = child.name in BLOCK_TAGS
            if block:
                parts.append("\n")
            _collect(child, parts)
            if block:
                parts.append("\n")
            elif child.name in CELL_TAGS:
                parts.append(" ")
        elif isinstance(child, NavigableString) and not isinstance(child, _SKIPPED_STRINGS):
            parts.append(re.sub(r"\s+", " ", str(child)))


def body_of(soup: BeautifulSoup) -> Tag:
    """The ``body`` element, or the whole document for a fragment."""
    body = soup.find("body")
    return body if isinstance(body, Tag) else soup


def page_title(soup: BeautifulSoup) -> str | None:
    """The first ``h1``, else ``<title>``, whitespace collapsed; None if both are empty."""
    for name in ("h1", "title"):
        tag = soup.find(name)
        if isinstance(tag, Tag):
            title = collapse_whitespace(tag.get_text(" "))
            if title:
                return title
    return None


def licence_of(text: str) -> str | None:
    """``cc_by_4_0`` or ``all_rights_reserved`` from the page's statements, else None.
    A CC BY sentence wins over a reserved-rights phrase on the same page."""
    folded = fold(collapse_whitespace(text))
    if any(fold(phrase) in folded for phrase in CC_BY_PHRASES):
        return "cc_by_4_0"
    if any(fold(phrase) in folded for phrase in ALL_RIGHTS_RESERVED_PHRASES):
        return "all_rights_reserved"
    return None


def has_app_root(soup: BeautifulSoup) -> bool:
    """An ``<app-root>`` element or an element with an ``ng-version`` attribute."""
    if soup.find("app-root") is not None:
        return True
    return soup.find(lambda tag: tag.has_attr("ng-version")) is not None


def is_client_shell(soup: BeautifulSoup, text: str) -> bool:
    """A client-side application root with less than 200 characters of visible body
    text (``text`` = :func:`html_text` of the cleaned body), docs/COLLECTORS.md §8.2."""
    return has_app_root(soup) and len(text) < CLIENT_SHELL_MAX_CHARS


def is_trap_link(tag: Tag) -> bool:
    """A hidden trap link: ``rel=nofollow`` together with ``aria-hidden`` (SOURCES §2)."""
    rel = tag.get("rel")
    values = rel if isinstance(rel, list) else str(rel or "").split()
    return "nofollow" in [value.lower() for value in values] and tag.has_attr("aria-hidden")


def extract_links(root: Tag, base_url: str, selector: str = "a[href]") -> list[PageLink]:
    """The links of the elements matching ``selector`` (default: every ``a[href]``), as
    absolute http(s) URLs resolved against ``base_url``, in document order. Trap links and
    ``/cdn-cgi/`` paths are dropped; collectors never follow them (docs/COLLECTORS.md §4.1)."""
    links: list[PageLink] = []
    for tag in root.select(selector):
        href = tag.get("href")
        if not isinstance(href, str) or is_trap_link(tag):
            continue
        absolute = outbound_href(urljoin(base_url, href.strip()))
        if absolute is None or urlsplit(absolute).path.startswith(TRAP_PATH_PREFIX):
            continue
        links.append(PageLink(absolute, collapse_whitespace(tag.get_text(" "))))
    return links


def read_page(snapshot: Snapshot) -> HtmlPage:
    """Decode, parse and clean a stored HTML response and read its generic text, title,
    licence statement and the client-shell rule."""
    decoded = decode_html(snapshot.body, snapshot.headers.get("content-type"))
    soup = parse_html(decoded.text)
    remove_hidden(soup)
    text = html_text(body_of(soup))
    return HtmlPage(
        soup=soup,
        text=text,
        title=page_title(soup),
        licence=licence_of(text),
        client_shell=is_client_shell(soup, text),
        warnings=decoded.warnings,
    )
