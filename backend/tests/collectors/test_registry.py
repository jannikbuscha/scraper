"""Collector modules by name (docs/COLLECTORS.md §2)."""

from __future__ import annotations

import sys
import types

import pytest

from mdt.collectors import registry
from mdt.collectors.base import TypeDeclaration
from mdt.collectors.registry import CollectorDefinitionError
from tests.collectors.stubs import StubCollector


def test_names_without_a_module_or_without_collector_are_not_implemented() -> None:
    assert registry.resolve("no_such_collector_module") is None
    assert registry.resolve("urls") is None  # a framework module without COLLECTOR


def test_a_module_with_collector_is_resolved_and_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("mdt.collectors.example_module")
    module.COLLECTOR = StubCollector(NAME="example_module")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mdt.collectors.example_module", module)
    assert registry.resolve("example_module") is module.COLLECTOR  # type: ignore[attr-defined]
    module.COLLECTOR = StubCollector(NAME="other")  # type: ignore[attr-defined]
    with pytest.raises(CollectorDefinitionError, match="NAME is 'other'"):
        registry.resolve("example_module")


@pytest.mark.parametrize(
    ("collector", "message"),
    [
        (StubCollector(VERSION=0), "VERSION must be a positive integer"),
        (StubCollector(MODES=("weekly",)), "unknown modes"),
        (StubCollector(PARAMS=frozenset({"speed"})), "unknown parameters"),
        (
            StubCollector(DECLARATION={"comment": TypeDeclaration(True, frozenset())}),
            "unknown entity type",
        ),
        (
            StubCollector(DECLARATION={"document": TypeDeclaration(True, frozenset({"colour"}))}),
            "document has no fields ['colour']",
        ),
        (
            StubCollector(
                DECLARATION={
                    "document": TypeDeclaration(True, frozenset({"title"}), match_rules=("name",))
                }
            ),
            "unknown match rules",
        ),
    ],
)
def test_invalid_collectors_are_refused(collector: StubCollector, message: str) -> None:
    with pytest.raises(CollectorDefinitionError) as raised:
        registry.register("stub", collector)
    assert message in str(raised.value)
    assert registry.resolve("stub") is None


def test_registered_collectors_win_and_are_removed_again() -> None:
    collector = StubCollector()
    with registry.registered("stub", collector):
        assert registry.resolve("stub") is collector
    assert registry.resolve("stub") is None
