"""Counters and run messages of one write unit of a collector run.

A write unit of the reconciler collects what it did (``stats`` counters, run messages)
here and hands it to the run's :class:`~mdt.collectors.base.RunScope` only after it has
committed, so a unit that fails and rolls back reports nothing it did not do
(docs/DATA_MODEL.md §15.11, docs/COLLECTORS.md §6.6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mdt.collectors.base import MessageLevel, RunScope


@dataclass(frozen=True)
class PendingMessage:
    """A run message waiting for its unit to commit."""

    level: MessageLevel
    code: str
    text: str
    url: str | None = None
    snapshot_id: str | None = None
    subject_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class RunEffects:
    """What one write unit of a run did, reported after it committed."""

    counts: Counter[str] = field(default_factory=Counter)
    messages: list[PendingMessage] = field(default_factory=list)

    def count(self, key: str, n: int = 1) -> None:
        """Add ``n`` to the ``stats`` counter ``key``."""
        if n:
            self.counts[key] += n

    def message(
        self,
        level: MessageLevel,
        code: str,
        text: str,
        *,
        url: str | None = None,
        snapshot_id: str | None = None,
        subject_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue a run message (docs/COLLECTORS.md §6.6)."""
        self.messages.append(
            PendingMessage(level, code, text, url, snapshot_id, subject_id, dict(details or {}))
        )

    def report(self, scope: RunScope) -> None:
        """Hand the counters and messages to the run, then forget them."""
        for key, n in self.counts.items():
            scope.count(key, n)
        for item in self.messages:
            scope.message(
                item.level,
                item.code,
                item.text,
                url=item.url,
                snapshot_id=item.snapshot_id,
                subject_id=item.subject_id,
                details=item.details,
            )
        self.counts.clear()
        self.messages.clear()
