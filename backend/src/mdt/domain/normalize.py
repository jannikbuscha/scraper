"""Normalisation of API values per field type (docs/DATA_MODEL.md §1.2 and §1.3).

The rules apply on every channel, before validation, comparison and storage. A value
that cannot be normalised is reported to a :class:`~mdt.domain.errors.Problems`
collector under its field path; messages never repeat the submitted value.
"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from collections.abc import Callable
from typing import Any, Final

from mdt.domain.clock import normalize_timestamp_input
from mdt.domain.dates import PartialDateError, parse_iso_date, parse_partial_date
from mdt.domain.errors import Problems
from mdt.domain.ids import ID_RE
from mdt.domain.registry import PREFIXES, FieldSpec
from mdt.domain.urls import UrlError, normalize_url

# Limits (DATA_MODEL §1.3).
MAX_LIST_ITEMS: Final = 200
MAX_ALIASES: Final = 100
MAX_EXCLUDE_PATTERNS: Final = 20
MAX_EXCLUDE_PATTERN_LENGTH: Final = 200
MAX_JSON_BYTES: Final = 64 * 1024
MAX_JSON_DEPTH: Final = 10
MAX_NOTE_CHARS: Final = 2000

ALIAS_KINDS: Final = ("name", "inflection", "abbreviation", "domain")
LINK_ORIGINS: Final = ("auto", "manual")
LINK_STATES: Final = ("suggested", "confirmed", "rejected")
LINK_READ_ONLY_KEYS: Final = ("matched_aliases", "match_count", "snippet")
_ALIAS_KEYS: Final = frozenset({"text", "lang", "case_sensitive", "kind", "exclude_patterns"})
_LINK_KEYS: Final = frozenset({"subject_id", "origin", "state", *LINK_READ_ONLY_KEYS})
_SOURCE_CATEGORY_KEYS: Final = frozenset({"source", "label", "url"})

_C0 = re.compile(r"[\x00-\x1f]")
_C0_EXCEPT_TAB_LF = re.compile(r"[\x00-\x08\x0b-\x1f]")
#: Unpaired UTF-16 surrogates (category Cs). JSON escapes such as ``"\ud800"`` (and
#: raw surrogate bytes, which ``json.loads`` decodes with ``surrogatepass``) produce
#: them, but they are not Unicode characters: they cannot be encoded as UTF-8, so
#: SQLite refuses them.
_SURROGATE = re.compile(r"[\ud800-\udfff]")
UNPAIRED_SURROGATE_MESSAGE: Final = "must be valid Unicode text (it contains an unpaired surrogate)"
_SURROGATE_KEY_MESSAGE: Final = "has a key that is not valid Unicode text (an unpaired surrogate)"


class _Invalid:
    """Marker for a value that failed normalisation (problems were recorded)."""

    def __repr__(self) -> str:
        return "INVALID"


INVALID: Final = _Invalid()


class ValueProblem(ValueError):
    """A normalisation problem of a single (scalar) value."""


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def has_unpaired_surrogate(value: str) -> bool:
    """True if ``value`` contains a lone UTF-16 surrogate (not valid Unicode text)."""
    return _SURROGATE.search(value) is not None


def unpaired_surrogate_problems(value: Any, path: str = "") -> dict[str, list[str]]:
    """``{path: [message]}`` for every string, and every object key, in a parsed JSON
    value that contains an unpaired surrogate. Paths are dotted (``data.name_en``,
    ``items[0].id``); a bad key is reported at the object that holds it, so no path
    repeats the invalid text. An empty result means the value is valid Unicode text."""
    problems: dict[str, list[str]] = {}

    def visit(item: Any, where: str) -> None:
        if isinstance(item, str):
            if has_unpaired_surrogate(item):
                problems.setdefault(where or "body", []).append(UNPAIRED_SURROGATE_MESSAGE)
        elif isinstance(item, dict):
            for key, child in item.items():
                if isinstance(key, str) and has_unpaired_surrogate(key):
                    messages = problems.setdefault(where or "body", [])
                    if _SURROGATE_KEY_MESSAGE not in messages:
                        messages.append(_SURROGATE_KEY_MESSAGE)
                    continue
                visit(child, f"{where}.{key}" if where else str(key))
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{where}[{index}]")

    visit(value, path)
    return problems


def _check_text(value: str) -> None:
    if has_unpaired_surrogate(value):
        raise ValueProblem(UNPAIRED_SURROGATE_MESSAGE)


def normalize_string(value: Any, max_length: int = 500) -> str | None:
    """Single-line string: NFC, trimmed, ``''`` → None, no C0 control characters and no
    unpaired surrogates."""
    if not isinstance(value, str):
        raise ValueProblem("must be a string")
    _check_text(value)
    result = _nfc(value).strip()
    if not result:
        return None
    if _C0.search(result):
        raise ValueProblem("must not contain control characters or line breaks")
    if len(result) > max_length:
        raise ValueProblem(f"must be at most {max_length} characters")
    return result


def normalize_text(value: Any, max_length: int = 20_000) -> str | None:
    """Multi-line text: NFC, CRLF/CR → LF, trimmed, ``''`` → None; C0 controls other
    than tab and newline, and unpaired surrogates, are refused."""
    if not isinstance(value, str):
        raise ValueProblem("must be a string")
    _check_text(value)
    result = _nfc(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not result:
        return None
    if _C0_EXCEPT_TAB_LF.search(result):
        raise ValueProblem("must not contain control characters")
    if len(result) > max_length:
        raise ValueProblem(f"must be at most {max_length} characters")
    return result


def normalize_note(value: Any) -> str | None:
    """A revision note: text rules, at most 2 000 characters."""
    if value is None:
        return None
    return normalize_text(value, MAX_NOTE_CHARS)


def _normalize_url(value: Any) -> str | None:
    if not isinstance(value, str):
        raise ValueProblem("must be a string")
    if not value.strip():
        return None
    try:
        return normalize_url(value)
    except UrlError as exc:
        raise ValueProblem(str(exc)) from exc


def _normalize_scalar_string(spec: FieldSpec, value: Any) -> str | None:
    result = normalize_string(value, spec.max_length or 500)
    if result is not None and spec.upper:
        result = result.upper()
    if result is not None and spec.pattern and not re.fullmatch(spec.pattern, result):
        raise ValueProblem(_pattern_message(spec))
    return result


def _pattern_message(spec: FieldSpec) -> str:
    if spec.type == "slug":
        return "must contain only lower-case letters, digits and single hyphens"
    if spec.name == "country":
        return "must be an ISO 3166-1 alpha-2 code"
    return "has an invalid format"


def _normalize_text_field(spec: FieldSpec, value: Any) -> str | None:
    return normalize_text(value, spec.max_length or 20_000)


def _normalize_bool(spec: FieldSpec, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueProblem("must be true or false")
    return value


def _normalize_int(spec: FieldSpec, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueProblem("must be an integer")
    if not -(2**63) <= value < 2**63:
        raise ValueProblem("is out of range")
    return value


def _normalize_number(spec: FieldSpec, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueProblem("must be a number")
    try:
        result = float(value)
    except OverflowError as exc:  # a JSON integer beyond the float range (about 1.8e308)
        raise ValueProblem("must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueProblem("must be a finite number")
    return result


def normalize_code(value: Any) -> str | None:
    """A vocabulary code: trimmed string, ``''`` → None."""
    if value is None:
        return None
    return normalize_string(value, 100)


def normalize_ref(value: Any, ref_types: tuple[str, ...] | None) -> str | None:
    """An entity ID of one of ``ref_types`` (checked by prefix)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueProblem("must be an ID")
    result = value.strip()
    if not result:
        return None
    match = ID_RE.fullmatch(result)
    if not match or PREFIXES.get(match.group("prefix")) is None:
        raise ValueProblem("must be a valid ID")
    if ref_types is not None and PREFIXES[match.group("prefix")] not in ref_types:
        raise ValueProblem("refers to a record of a type that is not allowed here")
    return result


def _normalize_date(spec: FieldSpec, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueProblem("must be a date (YYYY-MM-DD)")
    result = value.strip()
    if not result:
        return None
    try:
        return parse_iso_date(result).isoformat()
    except PartialDateError as exc:
        raise ValueProblem("must be a valid date (YYYY-MM-DD)") from exc


def _normalize_partial_date(spec: FieldSpec, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueProblem("must be a partial date")
    result = value.strip()
    if not result:
        return None
    try:
        return parse_partial_date(result).value
    except PartialDateError as exc:
        raise ValueProblem(
            "must be a valid date in the form YYYY, YYYY-Qn, YYYY-MM or YYYY-MM-DD"
        ) from exc


def _normalize_datetime(spec: FieldSpec, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueProblem("must be a timestamp")
    result = value.strip()
    if not result:
        return None
    try:
        return normalize_timestamp_input(result)
    except ValueError as exc:
        raise ValueProblem("must be an ISO 8601 timestamp with time zone") from exc


def _scalar(spec: FieldSpec, value: Any) -> Any:
    """Normalise one scalar value of ``spec``'s type (or element type for lists)."""
    kind = spec.type
    if value is None and kind not in ("bool",):
        return None
    if kind in ("string", "slug", "string_list"):
        return _normalize_scalar_string(spec, value)
    if kind == "text":
        return _normalize_text_field(spec, value)
    if kind in ("url", "url_list"):
        return _normalize_url(value)
    if kind in ("vocab", "vocab_list"):
        return normalize_code(value)
    if kind == "ref":
        return normalize_ref(value, spec.ref_types)
    handler = _SCALAR_HANDLERS.get(kind)
    if handler is None:
        raise ValueProblem("unsupported type")
    return handler(spec, value)


_SCALAR_HANDLERS: dict[str, Callable[[FieldSpec, Any], Any]] = {
    "bool": _normalize_bool,
    "int": _normalize_int,
    "number": _normalize_number,
    "date": _normalize_date,
    "partial_date": _normalize_partial_date,
    "datetime": _normalize_datetime,
}


def _dedupe(values: list[Any], key: Callable[[Any], Any] = lambda item: item) -> list[Any]:
    seen: set[Any] = set()
    result = []
    for item in values:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _normalize_plain_list(spec: FieldSpec, value: Any, path: str, problems: Problems) -> Any:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.add(path, "must be a list")
        return INVALID
    result = []
    failed = False
    for index, item in enumerate(value):
        try:
            normalized = _scalar(spec, item)
        except ValueProblem as exc:
            problems.add(f"{path}[{index}]", str(exc))
            failed = True
            continue
        if normalized is not None:
            result.append(normalized)
    if failed:
        return INVALID
    result = _dedupe(result)
    if len(result) > MAX_LIST_ITEMS:
        problems.add(path, f"must have at most {MAX_LIST_ITEMS} items")
        return INVALID
    return result


def _alias_patterns(raw: Any, path: str, errors: list[tuple[str, str]]) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.append((path, "must be a list"))
        return []
    patterns: list[str] = []
    for index, pattern in enumerate(raw):
        try:
            normalized = normalize_string(pattern, MAX_EXCLUDE_PATTERN_LENGTH)
        except ValueProblem as exc:
            errors.append((f"{path}[{index}]", str(exc)))
            continue
        if normalized is not None:
            patterns.append(normalized)
    patterns = _dedupe(patterns)
    if len(patterns) > MAX_EXCLUDE_PATTERNS:
        errors.append((path, f"must have at most {MAX_EXCLUDE_PATTERNS} items"))
    return patterns


def _normalize_alias(item: Any, path: str, problems: Problems) -> dict[str, Any] | _Invalid | None:
    """One alias item with defaults; None if its text is empty (the item is dropped)."""
    if not isinstance(item, dict):
        problems.add(path, "must be an object")
        return INVALID
    errors = [(f"{path}.{key}", "unknown key") for key in sorted(set(item) - _ALIAS_KEYS)]
    text: str | None = None
    lang: str | None = None
    try:
        text = normalize_string(item.get("text"))
    except ValueProblem as exc:
        errors.append((f"{path}.text", str(exc)))
    try:
        lang = normalize_string(item["lang"], 20) if item.get("lang") is not None else None
    except ValueProblem as exc:
        errors.append((f"{path}.lang", str(exc)))
    case_sensitive = item.get("case_sensitive", True)
    if not isinstance(case_sensitive, bool):
        errors.append((f"{path}.case_sensitive", "must be true or false"))
    kind = item.get("kind") or "name"
    if kind not in ALIAS_KINDS:
        errors.append((f"{path}.kind", f"must be one of {', '.join(ALIAS_KINDS)}"))
    patterns = _alias_patterns(item.get("exclude_patterns"), f"{path}.exclude_patterns", errors)
    if errors:
        for error_path, message in errors:
            problems.add(error_path, message)
        return INVALID
    if text is None:
        return None
    return {
        "text": text,
        "lang": lang,
        "case_sensitive": case_sensitive,
        "kind": kind,
        "exclude_patterns": patterns,
    }


def _normalize_alias_list(spec: FieldSpec, value: Any, path: str, problems: Problems) -> Any:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.add(path, "must be a list")
        return INVALID
    result: list[dict[str, Any]] = []
    failed = False
    for index, item in enumerate(value):
        normalized = _normalize_alias(item, f"{path}[{index}]", problems)
        if normalized is INVALID:
            failed = True
        elif isinstance(normalized, dict):
            result.append(normalized)
    if failed:
        return INVALID
    result = _dedupe(result, key=lambda alias: (alias["text"], alias["lang"]))
    if len(result) > MAX_ALIASES:
        problems.add(path, f"must have at most {MAX_ALIASES} items")
        return INVALID
    return result


def _normalize_link(item: Any, path: str, problems: Problems) -> dict[str, Any] | _Invalid:
    if not isinstance(item, dict):
        problems.add(path, "must be an object")
        return INVALID
    failed = False
    for key in sorted(set(item) - _LINK_KEYS):
        problems.add(f"{path}.{key}", "unknown key")
        failed = True
    try:
        subject_id = normalize_ref(item.get("subject_id"), ("project", "service"))
    except ValueProblem as exc:
        problems.add(f"{path}.subject_id", str(exc))
        return INVALID
    if subject_id is None:
        problems.add(f"{path}.subject_id", "is required")
        return INVALID
    origin = item.get("origin")
    if origin is not None and origin not in LINK_ORIGINS:
        problems.add(f"{path}.origin", f"must be one of {', '.join(LINK_ORIGINS)}")
        failed = True
    state = item.get("state")
    if state not in LINK_STATES:
        problems.add(f"{path}.state", f"must be one of {', '.join(LINK_STATES)}")
        failed = True
    result: dict[str, Any] = {"subject_id": subject_id, "origin": origin, "state": state}
    # Read-only keys: validated here; the write path ignores them on channel ui.
    if "matched_aliases" in item:
        aliases = item["matched_aliases"]
        if not isinstance(aliases, list) or not all(
            isinstance(a, str) and not has_unpaired_surrogate(a) for a in aliases
        ):
            problems.add(f"{path}.matched_aliases", "must be a list of strings")
            failed = True
        else:
            result["matched_aliases"] = _dedupe([a for a in aliases if a])
    if "match_count" in item:
        count = item["match_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            problems.add(f"{path}.match_count", "must be a non-negative integer")
            failed = True
        else:
            result["match_count"] = count
    if "snippet" in item:
        try:
            result["snippet"] = (
                normalize_text(item["snippet"]) if item["snippet"] is not None else None
            )
        except ValueProblem as exc:
            problems.add(f"{path}.snippet", str(exc))
            failed = True
    if failed:
        return INVALID
    return result


def _normalize_doc_links(spec: FieldSpec, value: Any, path: str, problems: Problems) -> Any:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.add(path, "must be a list")
        return INVALID
    links: list[dict[str, Any]] = []
    failed = False
    for index, item in enumerate(value):
        normalized = _normalize_link(item, f"{path}[{index}]", problems)
        if isinstance(normalized, dict):
            links.append(normalized)
        else:
            failed = True
    if failed:
        return INVALID
    subjects = [link["subject_id"] for link in links]
    if len(set(subjects)) != len(subjects):
        problems.add(path, "may contain at most one link per subject")
        return INVALID
    if len(links) > MAX_LIST_ITEMS:
        problems.add(path, f"must have at most {MAX_LIST_ITEMS} items")
        return INVALID
    return sorted(links, key=lambda link: link["subject_id"])


def _json_depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


def _check_json_types(value: Any) -> None:
    if isinstance(value, str):
        _check_text(value)
        return
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueProblem("must not contain NaN or infinite numbers")
        return
    if isinstance(value, list):
        for item in value:
            _check_json_types(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueProblem("object keys must be strings")
            if has_unpaired_surrogate(key):
                raise ValueProblem(_SURROGATE_KEY_MESSAGE)
            _check_json_types(item)
        return
    raise ValueProblem("must be JSON")


def canonical_json(value: Any) -> str:
    """Canonical serialisation used to compare JSON values (sorted keys)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_source_categories(value: Any, path: str, problems: Problems) -> Any:
    if not isinstance(value, list):
        problems.add(path, "must be a list of {source, label, url} objects")
        return INVALID
    result = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict) or set(item) - _SOURCE_CATEGORY_KEYS:
            problems.add(item_path, "must be an object with the keys source, label and url")
            return INVALID
        try:
            result.append(
                {
                    "source": normalize_string(item.get("source")),
                    "label": normalize_string(item.get("label")),
                    "url": _normalize_url(item.get("url")),
                }
            )
        except ValueProblem as exc:
            problems.add(item_path, str(exc))
            return INVALID
    return result


def _normalize_json(spec: FieldSpec, value: Any, path: str, problems: Problems) -> Any:
    if value is None:
        return None
    try:
        _check_json_types(value)
    except ValueProblem as exc:
        problems.add(path, str(exc))
        return INVALID
    if _json_depth(value) > MAX_JSON_DEPTH:
        problems.add(path, f"must not be nested deeper than {MAX_JSON_DEPTH} levels")
        return INVALID
    if len(canonical_json(value).encode("utf-8")) > MAX_JSON_BYTES:
        problems.add(path, f"must not be larger than {MAX_JSON_BYTES // 1024} KiB")
        return INVALID
    if spec.name == "source_categories":
        return _normalize_source_categories(value, path, problems)
    return copy.deepcopy(value)


def normalize_value(
    spec: FieldSpec, value: Any, problems: Problems, path: str | None = None
) -> Any:
    """Normalise ``value`` for ``spec``; returns :data:`INVALID` after recording problems."""
    path = path or spec.name
    if spec.type in ("url_list", "string_list", "vocab_list"):
        return _normalize_plain_list(spec, value, path, problems)
    if spec.type == "alias_list":
        return _normalize_alias_list(spec, value, path, problems)
    if spec.type == "doc_links":
        return _normalize_doc_links(spec, value, path, problems)
    if spec.type == "json":
        return _normalize_json(spec, value, path, problems)
    try:
        return _scalar(spec, value)
    except ValueProblem as exc:
        problems.add(path, str(exc))
        return INVALID


def is_empty(value: Any) -> bool:
    """Empty means None or an empty list; ``False`` and ``0`` are values (DATA_MODEL §1.2)."""
    return value is None or (isinstance(value, list) and not value)


def values_equal(spec: FieldSpec, left: Any, right: Any) -> bool:
    """Compare two normalised API values of ``spec`` (JSON by canonical serialisation)."""
    if spec.type == "json":
        return canonical_json(left) == canonical_json(right)
    if spec.is_list:
        return (left or []) == (right or [])
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return bool(left == right)
