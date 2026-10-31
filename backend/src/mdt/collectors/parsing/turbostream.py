"""Turbo-stream decoder for React Router v7 / Remix v2 single-fetch payloads
(docs/COLLECTORS.md §7.2; C1, C4).

thedigital.gov.ua renders its loader data into the page as JSON string literals passed to
``window.__reactRouterContext.streamController.enqueue("…")`` (Remix v2:
``window.__remixContext``); a ``.data`` request returns the same stream as the body. The
stream's first line is a JSON array in which values are referenced by index: an object is
``{"_<index of key>": <index of value>}``, an array lists indices, and negative numbers
are constants. Only the constructs seen in the captures are decoded: -5 is null and -7
is undefined (the key is left out). Any other constant, typed values (arrays that start
with a one-letter type tag), promise lines after the first line and circular references
raise :class:`~mdt.collectors.parsing.ParseError`, so an unknown construct fails loudly.

:func:`loader_data` returns the mapping of route ID to loader data for both inputs, and
:func:`find_route` picks an entry by its keys, never by the route ID, so a renamed route
does not break a parser. The ``root`` entry (menus, contacts) is never read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from mdt.collectors.parsing import ParseError

NULL = -5
UNDEFINED = -7
ROOT_ROUTE = "root"

#: ``….streamController.enqueue("<JSON string literal>")``.
_ENQUEUE = re.compile(
    r"window\.__(?:reactRouterContext|remixContext)\.streamController\.enqueue\(\s*"
    r'("(?:[^"\\]|\\.)*")\s*\)',
    re.DOTALL,
)
_UNDEFINED = object()


def stream_from_html(html: str) -> str:
    """The turbo-stream embedded in an HTML page: the enqueued string literals, decoded
    and concatenated in order. Raises ParseError when the page has none."""
    chunks: list[str] = []
    for match in _ENQUEUE.finditer(html):
        try:
            chunk = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ParseError("an enqueued turbo-stream chunk is not a string literal") from exc
        chunks.append(chunk)
    if not chunks:
        raise ParseError("the page embeds no turbo-stream (no streamController.enqueue call)")
    return "".join(chunks)


def decode(stream: str) -> Any:
    """Decode a turbo-stream: the value at index 0 of its first line."""
    first, _, rest = stream.lstrip("﻿").partition("\n")
    if rest.strip():
        raise ParseError("the turbo-stream has further lines (promises are not supported)")
    try:
        values = json.loads(first)
    except json.JSONDecodeError as exc:
        raise ParseError("the first turbo-stream line is not JSON") from exc
    if not isinstance(values, list) or not values:
        raise ParseError("the first turbo-stream line is not a non-empty JSON array")
    return _Decoder(values).value(0)


class _Decoder:
    """Resolves indices into Python values; shared references decode once."""

    def __init__(self, values: list[Any]) -> None:
        self.values = values
        self.done: dict[int, Any] = {}
        self.active: set[int] = set()

    def value(self, index: Any) -> Any:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ParseError("a turbo-stream reference is not an integer")
        if index < 0:
            return self.constant(index)
        if index >= len(self.values):
            raise ParseError(f"turbo-stream reference {index} is out of range")
        if index in self.done:
            return self.done[index]
        if index in self.active:
            raise ParseError("the turbo-stream has a circular reference")
        self.active.add(index)
        result = self.entry(self.values[index])
        self.active.discard(index)
        self.done[index] = result
        return result

    @staticmethod
    def constant(index: int) -> Any:
        if index == NULL:
            return None
        if index == UNDEFINED:
            return _UNDEFINED
        raise ParseError(f"unsupported turbo-stream constant {index}")

    def entry(self, raw: Any) -> Any:
        if isinstance(raw, dict):
            result: dict[str, Any] = {}
            for reference, value_index in raw.items():
                key = self.key(reference)
                value = self.value(value_index)
                if value is not _UNDEFINED:
                    result[key] = value
            return result
        if isinstance(raw, list):
            if raw and isinstance(raw[0], str):
                raise ParseError("unsupported turbo-stream typed value")
            items = [self.value(index) for index in raw]
            return [None if item is _UNDEFINED else item for item in items]
        return raw

    def key(self, reference: str) -> str:
        if not reference.startswith("_") or not reference[1:].isdigit():
            raise ParseError("a turbo-stream object key is not a reference")
        key = self.value(int(reference[1:]))
        if not isinstance(key, str):
            raise ParseError("a turbo-stream object key does not name a string")
        return key


def loader_data(text: str) -> dict[str, Any]:
    """The loader data of an HTML page or a ``.data`` body: route ID → data.

    An HTML page holds the mapping under ``loaderData``; a ``.data`` body decodes to
    ``{"<route ID>": {"data": …}}``, which is unwrapped to the same mapping.
    """
    stripped = text.lstrip("﻿").lstrip()
    stream = stripped if stripped.startswith("[") else stream_from_html(text)
    root = decode(stream)
    if not isinstance(root, dict):
        raise ParseError("the turbo-stream root is not an object")
    if "loaderData" in root:
        routes = root["loaderData"]
        if not isinstance(routes, dict):
            raise ParseError("loaderData is not an object")
        return routes
    unwrapped: dict[str, Any] = {}
    for route_id, entry in root.items():
        if not isinstance(entry, dict) or "data" not in entry:
            raise ParseError("the turbo-stream has neither loaderData nor route data entries")
        unwrapped[route_id] = entry["data"]
    return unwrapped


def find_route(
    routes: Mapping[str, Any], any_of: Iterable[str], *, required: Iterable[str] = ()
) -> tuple[str, dict[str, Any]]:
    """The first non-``root`` entry whose data has every ``required`` key and at least
    one of ``any_of`` (e.g. listing: ``required=("pagination",)``,
    ``any_of=("projects",)``; detail: ``any_of=("project",)``). Raises ParseError."""
    wanted = tuple(any_of)
    needed = tuple(required)
    for route_id, data in routes.items():
        if route_id == ROOT_ROUTE or not isinstance(data, dict):
            continue
        if all(key in data for key in needed) and any(key in data for key in wanted):
            return route_id, data
    keys = ", ".join([*needed, " | ".join(wanted)])
    raise ParseError(f"no loader entry with the keys {keys}")
