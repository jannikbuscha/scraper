"""A stub collector and a test ``sources.yaml`` for the framework tests (synthetic values
only; the stub never parses real data)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mdt.collectors.base import RunContext, TypeDeclaration

#: Collectors of the test sources file: an enabled stub with network, a disabled one and a
#: built-in one; their modules are registered by the tests.
TEST_SOURCES = {
    "version": 1,
    "defaults": {"min_interval_s": 1.0, "exclude_hosts": ["excluded.example.org"]},
    "collectors": {
        "stub": {
            "label": "Stub collector",
            "source": "S0",
            "licence": {"code": "unknown"},
            "hosts": {"slow.example.org": {"min_interval_s": 5.0}},
            "options": {"check_url": "https://example.org/start"},
            "fixtures": [
                {"name": "stub_page", "url": "https://example.org/page", "purpose": "a page"}
            ],
        },
        "stub_disabled": {"label": "Disabled stub", "enabled": False},
        "stub_builtin": {"label": "Built-in stub", "builtin": True},
        "stub_unimplemented": {"label": "Configured without a module"},
    },
}


def write_sources(directory: Path, data: Mapping[str, object] | None = None) -> Path:
    """Write a test ``sources.yaml`` and return its path."""
    path = directory / "sources.yaml"
    text = yaml.safe_dump(dict(data or TEST_SOURCES), allow_unicode=True, sort_keys=False)
    path.write_text(text, "utf-8")
    return path


Behaviour = Callable[[RunContext], None]


def _nothing(ctx: RunContext) -> None:
    return None


@dataclass
class StubCollector:
    """A collector whose ``run`` is a function the test provides."""

    NAME: str = "stub"
    VERSION: int = 1
    DECLARATION: Mapping[str, TypeDeclaration] = field(
        default_factory=lambda: {
            "document": TypeDeclaration(creates=True, writes=frozenset({"title"}))
        }
    )
    MODES: tuple[str, ...] = ("incremental", "full")
    PARAMS: frozenset[str] = frozenset({"limit", "refetch"})
    behaviour: Behaviour = _nothing
    calls: int = 0

    def run(self, ctx: RunContext) -> None:
        self.calls += 1
        self.behaviour(ctx)
