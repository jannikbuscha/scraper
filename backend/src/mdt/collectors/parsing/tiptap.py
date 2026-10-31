"""TipTap JSON to text and outbound links (docs/COLLECTORS.md §7.3; C1, C4).

thedigital.gov.ua stores page bodies (``blocks``) as TipTap/ProseMirror JSON. The walk is
depth-first over ``content``:

* ``text`` nodes are concatenated; ``paragraph``, ``heading``, ``listItem``,
  ``blockquote``, ``codeBlock`` and ``tableRow`` end their line; ``hardBreak`` is a line
  break (table cells are separated by a tab so that their words do not run together);
* text held in attributes: ``section`` → ``attrs.label.text`` and ``tabsItem`` →
  ``attrs.label`` as heading lines; ``linkListItem`` and ``buttonsItem`` → ``attrs.text``
  as a line; ``valueCardListItem`` → ``value``, ``unit`` and ``text`` (those present,
  space-separated) as a line;
* outbound links (absolute ``http``/``https`` only, so ``mailto:`` is dropped): ``link``
  marks with the marked text, and ``linkListItem``/``buttonsItem`` with ``attrs.href`` and
  ``attrs.text``;
* nothing from ``image``, ``gallery``, ``video``, ``embed``, ``teamMembers``,
  ``relatedDocuments`` (C4 reads those items as documents) or any other attribute.

The text is normalised as a document text (docs/DATA_MODEL.md §15.6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from mdt.collectors.parsing.texts import collapse_whitespace, normalize_document_text
from mdt.domain.urls import UrlError, normalize_url

LinkKind = Literal["mark", "linkListItem", "buttonsItem"]

#: Nodes whose line ends after their content.
LINE_NODES = frozenset({"paragraph", "heading", "listItem", "blockquote", "codeBlock", "tableRow"})
#: Nodes that give no text at all (their content is skipped too).
SKIPPED_NODES = frozenset({"image", "gallery", "video", "embed", "teamMembers", "relatedDocuments"})
_CELL_NODES = frozenset({"tableCell", "tableHeader"})
_ITEM_LINK_NODES: frozenset[str] = frozenset({"linkListItem", "buttonsItem"})


@dataclass(frozen=True)
class OutboundLink:
    """A link to an absolute http(s) URL: its target, its text and where it was found."""

    href: str
    text: str
    kind: LinkKind


@dataclass(frozen=True)
class TipTapText:
    """The plain text of a TipTap document and its outbound links in document order."""

    text: str
    links: tuple[OutboundLink, ...]


def outbound_href(value: Any) -> str | None:
    """A normalised absolute http(s) URL, or None for anything else (``mailto:``, relative
    paths, invalid URLs)."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return None
    try:
        return normalize_url(candidate)
    except UrlError:
        return None


def tiptap_to_text(document: Any) -> TipTapText:
    """Text and outbound links of a TipTap document: a ``doc`` node, any node, or a list
    of nodes (as in the ``blocks`` of thedigital.gov.ua); None gives an empty text."""
    walker = _Walker()
    walker.walk(document)
    walker.flush_link()
    return TipTapText(normalize_document_text("".join(walker.parts)), tuple(walker.links))


class _Walker:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.links: list[OutboundLink] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []

    # Output -----------------------------------------------------------------------------

    def end_line(self) -> None:
        self.flush_link()
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def line(self, text: str) -> None:
        text = collapse_whitespace(text)
        if text:
            self.end_line()
            self.parts.append(text)
            self.end_line()

    def flush_link(self) -> None:
        if self._link_href is not None:
            text = collapse_whitespace("".join(self._link_text))
            self.links.append(OutboundLink(self._link_href, text, "mark"))
        self._link_href = None
        self._link_text = []

    # Walk -------------------------------------------------------------------------------

    def walk(self, node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                self.walk(item)
            return
        if not isinstance(node, Mapping):
            return
        kind = node.get("type")
        if kind in SKIPPED_NODES:
            return
        attrs = node.get("attrs")
        attrs = attrs if isinstance(attrs, Mapping) else {}
        if kind == "text":
            self.text(node)
            return
        if kind == "hardBreak":
            self.flush_link()
            self.parts.append("\n")
            return
        self.attribute_text(kind, attrs)
        self.walk(node.get("content"))
        if kind in LINE_NODES:
            self.end_line()
        elif kind in _CELL_NODES:
            self.flush_link()
            self.parts.append("\t")

    def text(self, node: Mapping[str, Any]) -> None:
        value = node.get("text")
        if not isinstance(value, str):
            return
        href = None
        for mark in node.get("marks") or ():
            if isinstance(mark, Mapping) and mark.get("type") == "link":
                mark_attrs = mark.get("attrs")
                if isinstance(mark_attrs, Mapping):
                    href = outbound_href(mark_attrs.get("href"))
        if href != self._link_href:
            self.flush_link()
            self._link_href = href
        if href is not None:
            self._link_text.append(value)
        self.parts.append(value)

    def attribute_text(self, kind: Any, attrs: Mapping[str, Any]) -> None:
        if kind == "section":
            label = attrs.get("label")
            if isinstance(label, Mapping) and isinstance(label.get("text"), str):
                self.line(label["text"])
        elif kind == "tabsItem":
            if isinstance(attrs.get("label"), str):
                self.line(attrs["label"])
        elif kind in _ITEM_LINK_NODES:
            raw_text = attrs.get("text")
            text = raw_text if isinstance(raw_text, str) else ""
            self.line(text)
            href = outbound_href(attrs.get("href"))
            if href is not None:
                self.links.append(OutboundLink(href, collapse_whitespace(text), kind))
        elif kind == "valueCardListItem":
            values = [attrs.get(key) for key in ("value", "unit", "text")]
            self.line(" ".join(str(value) for value in values if isinstance(value, str | int)))
