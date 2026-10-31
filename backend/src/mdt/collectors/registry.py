"""Collector modules by name (docs/COLLECTORS.md §2).

A collector is the module ``mdt.collectors.<name>``, which exposes ``COLLECTOR`` (an object
satisfying :class:`~mdt.collectors.base.Collector` whose ``NAME`` is ``<name>``). Only names
that ``sources.yaml`` configures are ever resolved. A configured name without such a module
or without ``COLLECTOR`` in it (the Phase 2 collectors arrive one by one) is "not
implemented": it is not listed and cannot be started. A ``COLLECTOR`` that does not satisfy
the interface raises :class:`CollectorDefinitionError`. Tests register stub collectors with
:func:`register`.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager

from mdt.collectors.base import MATCH_RULES, RUN_MODES, Collector
from mdt.domain.registry import ENTITY_TYPES

#: The run parameters of docs/COLLECTORS.md §6.4.
KNOWN_PARAMS = frozenset({"limit", "refetch", "recall_sample", "recall_seed", "document_ids"})

_registered: dict[str, Collector] = {}


class CollectorDefinitionError(RuntimeError):
    """A collector module does not satisfy the interface of docs/COLLECTORS.md §2.1."""


def resolve(name: str) -> Collector | None:
    """The collector of ``name``, or None if no module implements it."""
    if name in _registered:
        return _registered[name]
    module_name = f"mdt.collectors.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise
    collector = getattr(module, "COLLECTOR", None)
    if collector is None:  # a helper module of the same name (e.g. tagger.py) not yet a collector
        return None
    check_collector(name, collector)
    return collector  # type: ignore[no-any-return]


def check_collector(name: str, collector: Collector) -> None:
    """Refuse a collector whose name, modes, parameters or declaration are not valid."""
    where = f"collector {name}"
    if name != collector.NAME:
        raise CollectorDefinitionError(f"{where}: NAME is {collector.NAME!r}")
    version = collector.VERSION
    if not isinstance(version, int) or version < 1:
        raise CollectorDefinitionError(f"{where}: VERSION must be a positive integer")
    if set(collector.MODES) - set(RUN_MODES):
        raise CollectorDefinitionError(f"{where}: unknown modes {sorted(collector.MODES)}")
    if set(collector.PARAMS) - KNOWN_PARAMS:
        raise CollectorDefinitionError(f"{where}: unknown parameters {sorted(collector.PARAMS)}")
    for entity_type, declaration in collector.DECLARATION.items():
        spec = ENTITY_TYPES.get(entity_type)
        if spec is None or not spec.curated:
            raise CollectorDefinitionError(f"{where}: unknown entity type {entity_type!r}")
        unknown = (declaration.writes | declaration.propose_only) - {
            field.name for field in spec.fields
        }
        if unknown:
            raise CollectorDefinitionError(
                f"{where}: {entity_type} has no fields {sorted(unknown)}"
            )
        if set(declaration.match_rules) - set(MATCH_RULES):
            raise CollectorDefinitionError(f"{where}: unknown match rules")


def register(name: str, collector: Collector) -> None:
    """Make ``collector`` the implementation of ``name`` (tests)."""
    check_collector(name, collector)
    _registered[name] = collector


def unregister(name: str) -> None:
    """Undo :func:`register`."""
    _registered.pop(name, None)


@contextmanager
def registered(name: str, collector: Collector) -> Iterator[Collector]:
    """:func:`register` for the duration of a ``with`` block."""
    register(name, collector)
    try:
        yield collector
    finally:
        unregister(name)
