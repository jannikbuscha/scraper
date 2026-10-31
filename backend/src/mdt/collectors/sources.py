"""``sources.yaml``: the operational settings of the collectors (docs/COLLECTORS.md §3).

The file holds settings only (intervals, timeouts, limits, hosts, licences, options and
fixture lists); what a collector parses and may write is code. It is validated when the
app starts and by every CLI command that uses it: an invalid file raises
:class:`SourcesError` with a message that names the offending key.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from mdt.collectors.urls import UrlError, normalize_host, parse_fetch_url

#: Collector names: module names of ``mdt.collectors`` (docs/COLLECTORS.md §1).
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CODE_RE = re.compile(r"^[a-z0-9_]+$")
_FIXTURE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
#: ``source_id`` of manual uploads and fetches, never a collector name.
MANUAL = "manual"
#: Modules of the framework, which can never be collector names.
RESERVED_NAMES = frozenset(
    {"base", "client", "parsing", "registry", "replay", "robots", "runs", "sources", "store"}
    | {"urls", "duplicates", "errors", "fetchlog", "fixtures", "run_context", "sourcecheck"}
    | {"throttle", MANUAL}
)


class SourcesError(ValueError):
    """``sources.yaml`` is missing or invalid; the message says where."""


@dataclass(frozen=True)
class ClientSettings:
    """Client and reconciliation defaults of a collector (``defaults``, overridable)."""

    min_interval_s: float = 1.0
    timeout_connect_s: float = 10.0
    timeout_read_s: float = 30.0
    max_bytes: int = 26_214_400
    max_redirects: int = 5
    retries: int = 2
    backoff_base_s: float = 5.0
    max_wait_s: float = 600.0
    discontinued_after_runs: int = 2


#: ``defaults`` keys: (type, minimum, minimum allowed) per key.
_SETTING_RULES: dict[str, tuple[type, float, bool]] = {
    "min_interval_s": (float, 0.0, True),
    "timeout_connect_s": (float, 0.0, False),
    "timeout_read_s": (float, 0.0, False),
    "max_bytes": (int, 1, True),
    "max_redirects": (int, 0, True),
    "retries": (int, 0, True),
    "backoff_base_s": (float, 0.0, True),
    "max_wait_s": (float, 0.0, True),
    "discontinued_after_runs": (int, 1, True),
}
_ENTRY_KEYS = frozenset(
    {
        "label",
        "source",
        "enabled",
        "needs_server_check",
        "hosts",
        "exclude_hosts",
        "licence",
        "options",
        "fixtures",
        "builtin",
    }
    | set(_SETTING_RULES)
)


@dataclass(frozen=True)
class Licence:
    """Default licence of a source's documents: a ``license`` code and the statement as
    captured (docs/SOURCES.md)."""

    code: str
    statement: str | None = None


@dataclass(frozen=True)
class FixtureSpec:
    """One entry of a collector's ``fixtures`` list (``mdt fixtures capture``)."""

    name: str
    url: str
    purpose: str


@dataclass(frozen=True)
class CollectorConfig:
    """The effective settings of one collector (defaults merged with its entry)."""

    name: str
    label: str
    source: str | None
    enabled: bool
    builtin: bool
    needs_server_check: bool
    settings: ClientSettings
    host_intervals: Mapping[str, float]
    exclude_hosts: frozenset[str]
    licence: Licence
    options: Mapping[str, Any]
    fixtures: tuple[FixtureSpec, ...]
    #: SHA-256 of the canonical JSON of the collector's entry and the defaults.
    entry_hash: str = field(repr=False)

    def min_interval(self, host: str) -> float:
        """The configured interval of ``host`` (the per-host value, else the default)."""
        return self.host_intervals.get(host, self.settings.min_interval_s)


@dataclass(frozen=True)
class SourcesConfig:
    """The whole file. ``manual`` is the configuration of manual fetches
    (docs/COLLECTORS.md §10.3): the defaults, with every host interval that a collector
    configures (the largest one per host)."""

    path: Path
    version: int
    collectors: Mapping[str, CollectorConfig]
    manual: CollectorConfig

    def get(self, name: str) -> CollectorConfig | None:
        """The configuration of ``name``, or None if the file has no such entry."""
        return self.collectors.get(name)


def load_sources(path: Path) -> SourcesConfig:
    """Read and validate ``path`` (cached while the file is unchanged)."""
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise SourcesError(f"{path} is missing") from exc
    return _load_cached(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _load_cached(path: str, _mtime_ns: int, _size: int) -> SourcesConfig:
    file = Path(path)
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SourcesError(f"{file.name}: cannot be read as YAML ({type(exc).__name__})") from exc
    return parse_sources(data, file)


def parse_sources(data: Any, path: Path) -> SourcesConfig:
    """Validate the parsed YAML document ``data``."""
    where = path.name
    if not isinstance(data, Mapping):
        raise SourcesError(f"{where}: expected a mapping")
    unknown = set(data) - {"version", "defaults", "collectors"}
    if unknown:
        raise SourcesError(f"{where}: unknown keys {sorted(map(str, unknown))}")
    if data.get("version") != 1:
        raise SourcesError(f"{where}: version must be 1")
    defaults = _mapping(data.get("defaults", {}), f"{where}: defaults")
    unknown = set(defaults) - set(_SETTING_RULES) - {"exclude_hosts"}
    if unknown:
        raise SourcesError(f"{where}: defaults: unknown keys {sorted(map(str, unknown))}")
    base_settings = _settings(defaults, ClientSettings(), f"{where}: defaults")
    base_excluded = _hosts(defaults.get("exclude_hosts", []), f"{where}: defaults.exclude_hosts")
    collectors = _mapping(data.get("collectors"), f"{where}: collectors")
    if not collectors:
        raise SourcesError(f"{where}: collectors must not be empty")
    parsed: dict[str, CollectorConfig] = {}
    for name, entry in collectors.items():
        prefix = f"{where}: collectors.{name}"
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in RESERVED_NAMES:
            raise SourcesError(f"{prefix}: invalid collector name")
        parsed[name] = _collector(
            name, entry, defaults, base_settings, base_excluded, prefix=prefix
        )
    intervals: dict[str, float] = {}
    for config in parsed.values():
        for host, interval in config.host_intervals.items():
            intervals[host] = max(interval, intervals.get(host, 0.0))
    manual = CollectorConfig(
        name=MANUAL,
        label="Manual fetch",
        source=None,
        enabled=True,
        builtin=False,
        needs_server_check=False,
        settings=base_settings,
        host_intervals=intervals,
        exclude_hosts=base_excluded,
        licence=Licence(code="unknown"),
        options={},
        fixtures=(),
        entry_hash=_digest({"defaults": dict(defaults)}),
    )
    return SourcesConfig(path=path, version=1, collectors=parsed, manual=manual)


def _collector(
    name: str,
    entry: Any,
    defaults: Mapping[str, Any],
    base: ClientSettings,
    base_excluded: frozenset[str],
    *,
    prefix: str,
) -> CollectorConfig:
    entry = _mapping(entry, prefix)
    unknown = set(entry) - _ENTRY_KEYS
    if unknown:
        raise SourcesError(f"{prefix}: unknown keys {sorted(map(str, unknown))}")
    label = entry.get("label")
    if not isinstance(label, str) or not label.strip():
        raise SourcesError(f"{prefix}.label: a non-empty string is required")
    source = entry.get("source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise SourcesError(f"{prefix}.source: must be a string")
    flags = {key: entry.get(key, key == "enabled") for key in ("enabled", "builtin")}
    flags["needs_server_check"] = entry.get("needs_server_check", False)
    for key, value in flags.items():
        if not isinstance(value, bool):
            raise SourcesError(f"{prefix}.{key}: must be true or false")
    host_intervals: dict[str, float] = {}
    for host, settings in _mapping(entry.get("hosts", {}), f"{prefix}.hosts").items():
        where = f"{prefix}.hosts.{host}"
        settings = _mapping(settings, where)
        if set(settings) - {"min_interval_s"}:
            raise SourcesError(f"{where}: only min_interval_s can be set per host")
        value = _number(settings.get("min_interval_s"), f"{where}.min_interval_s", float, 0.0)
        host_intervals[_host(host, where)] = float(value)
    excluded = base_excluded | _hosts(entry.get("exclude_hosts", []), f"{prefix}.exclude_hosts")
    return CollectorConfig(
        name=name,
        label=label.strip(),
        source=source.strip() if isinstance(source, str) else None,
        enabled=flags["enabled"],
        builtin=flags["builtin"],
        needs_server_check=flags["needs_server_check"],
        settings=_settings(entry, base, prefix),
        host_intervals=host_intervals,
        exclude_hosts=excluded,
        licence=_licence(entry.get("licence"), f"{prefix}.licence"),
        options=dict(_mapping(entry.get("options", {}), f"{prefix}.options")),
        fixtures=_fixtures(entry.get("fixtures", []), f"{prefix}.fixtures"),
        entry_hash=_digest({"defaults": dict(defaults), "entry": dict(entry)}),
    )


def _settings(values: Mapping[str, Any], base: ClientSettings, prefix: str) -> ClientSettings:
    changes: dict[str, Any] = {}
    for key, (kind, minimum, inclusive) in _SETTING_RULES.items():
        if key in values:
            number = _number(values[key], f"{prefix}.{key}", kind, minimum, inclusive=inclusive)
            changes[key] = kind(number)
    return ClientSettings(**{**base.__dict__, **changes})


def _number(
    value: Any, where: str, kind: type, minimum: float, *, inclusive: bool = True
) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SourcesError(f"{where}: a number is required")
    if kind is int and not isinstance(value, int):
        raise SourcesError(f"{where}: an integer is required")
    if value < minimum or (not inclusive and value == minimum):
        relation = "at least" if inclusive else "greater than"
        raise SourcesError(f"{where}: must be {relation} {minimum:g}")
    return value


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourcesError(f"{where}: expected a mapping")
    return value


def _host(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise SourcesError(f"{where}: host names must be strings")
    try:
        return normalize_host(value)
    except UrlError as exc:
        raise SourcesError(f"{where}: invalid host name") from exc


def _hosts(value: Any, where: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise SourcesError(f"{where}: expected a list of host names")
    return frozenset(_host(item, where) for item in value)


def _licence(value: Any, where: str) -> Licence:
    if value is None:
        return Licence(code="unknown")
    value = _mapping(value, where)
    if set(value) - {"code", "statement"}:
        raise SourcesError(f"{where}: only code and statement can be set")
    code = value.get("code")
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        raise SourcesError(f"{where}.code: a license vocabulary code is required")
    statement = value.get("statement")
    if statement is not None and not isinstance(statement, str):
        raise SourcesError(f"{where}.statement: must be a string")
    return Licence(code=code, statement=statement)


def _fixtures(value: Any, where: str) -> tuple[FixtureSpec, ...]:
    if not isinstance(value, list):
        raise SourcesError(f"{where}: expected a list")
    fixtures: list[FixtureSpec] = []
    for index, item in enumerate(value):
        item_where = f"{where}[{index}]"
        item = _mapping(item, item_where)
        if set(item) != {"name", "url", "purpose"}:
            raise SourcesError(f"{item_where}: name, url and purpose are required")
        name, url, purpose = item["name"], item["url"], item["purpose"]
        if not isinstance(name, str) or not _FIXTURE_NAME_RE.fullmatch(name):
            raise SourcesError(f"{item_where}.name: invalid fixture name")
        if not isinstance(purpose, str) or not purpose.strip():
            raise SourcesError(f"{item_where}.purpose: a non-empty string is required")
        try:
            normalised = parse_fetch_url(str(url)).url
        except UrlError as exc:
            raise SourcesError(f"{item_where}.url: {exc}") from exc
        fixtures.append(FixtureSpec(name=name, url=normalised, purpose=purpose.strip()))
    names = [fixture.name for fixture in fixtures]
    if len(set(names)) != len(names):
        raise SourcesError(f"{where}: fixture names must be unique")
    return tuple(fixtures)


def _digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
