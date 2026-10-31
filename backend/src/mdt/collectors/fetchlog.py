"""Where the polite client records what it does (docs/COLLECTORS.md §4.9).

:class:`DatabaseSink` writes one ``fetch_log`` row per attempt (each its own small write
unit) and stores final response bodies in the snapshot store; it forwards run messages and
counters to the run. :class:`MemorySink` keeps everything in memory and writes nothing to
the database (``mdt fixtures capture``, ``mdt sources check``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import insert
from sqlalchemy.orm import Session

from mdt.collectors.base import MessageLevel, Snapshot
from mdt.collectors.store import SnapshotMeta, SnapshotRecord, SnapshotStore, kept_headers
from mdt.db.models import FetchLog
from mdt.db.session import write_transaction
from mdt.domain.clock import utc_now


@dataclass(frozen=True)
class FetchEntry:
    """One ``fetch_log`` row (DATA_MODEL §14.3)."""

    at: str
    method: str
    url: str
    host: str
    purpose: str
    outcome: str
    attempt: int = 1
    status: int | None = None
    bytes: int | None = None
    duration_ms: int | None = None
    raw_snapshot_id: str | None = None
    retry_after_s: float | None = None
    error: str | None = None


class FetchSink(Protocol):
    """Where a client records what it does."""

    def record_fetch(self, entry: FetchEntry) -> None:
        """Write one fetch-log row."""
        ...

    def store(self, body: bytes, meta: SnapshotMeta) -> Snapshot:
        """Keep a final response body; return it as parser input."""
        ...

    def conditional_base(self, url: str) -> SnapshotRecord | None:
        """The latest live 200 snapshot of ``url`` (for conditional requests), or None."""
        ...

    def open(self, raw_id: str) -> Snapshot:
        """A stored snapshot with its body."""
        ...

    def message(
        self,
        level: MessageLevel,
        code: str,
        text: str,
        *,
        url: str | None = None,
        snapshot_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """A run message (dropped outside runs)."""
        ...

    def count(self, key: str, n: int = 1) -> None:
        """Add to a run counter (dropped outside runs)."""
        ...


class RunHooks(Protocol):
    """The part of a run a :class:`DatabaseSink` reports to."""

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
        """A run message."""
        ...

    def count(self, key: str, n: int = 1) -> None:
        """A run counter."""
        ...


class DatabaseSink:
    """Records into ``fetch_log`` and the snapshot store (runs and manual fetches)."""

    def __init__(
        self,
        session: Session,
        store: SnapshotStore,
        *,
        run_id: str | None,
        hooks: RunHooks | None = None,
    ) -> None:
        self.session = session
        self.snapshots = store
        self.run_id = run_id
        self.hooks = hooks

    def record_fetch(self, entry: FetchEntry) -> None:
        """One small write unit per row."""
        values = {**entry.__dict__, "run_id": self.run_id}
        with write_transaction(self.session):
            self.session.execute(insert(FetchLog).values(**values))

    def store(self, body: bytes, meta: SnapshotMeta) -> Snapshot:
        """Store the body and its row."""
        return self.snapshots.put(self.session, body, meta)

    def conditional_base(self, url: str) -> SnapshotRecord | None:
        """The newest live 200 snapshot of ``url``."""
        return self.snapshots.latest_for_url(self.session, url, via="live", status=200)

    def open(self, raw_id: str) -> Snapshot:
        """Load a stored snapshot."""
        return self.snapshots.open(self.session, raw_id)

    def message(
        self,
        level: MessageLevel,
        code: str,
        text: str,
        *,
        url: str | None = None,
        snapshot_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Forward to the run, if any."""
        if self.hooks is not None:
            self.hooks.message(level, code, text, url=url, snapshot_id=snapshot_id, details=details)

    def count(self, key: str, n: int = 1) -> None:
        """Forward to the run, if any."""
        if self.hooks is not None:
            self.hooks.count(key, n)


class MemorySink:
    """Keeps everything in memory and writes nothing to the database."""

    def __init__(self) -> None:
        self.fetches: list[FetchEntry] = []
        self.snapshots: dict[str, Snapshot] = {}
        self.messages: list[tuple[str, str, str]] = []
        self.counts: dict[str, int] = {}

    def record_fetch(self, entry: FetchEntry) -> None:
        """Keep the row."""
        self.fetches.append(entry)

    def store(self, body: bytes, meta: SnapshotMeta) -> Snapshot:
        """Keep the body under a memory-only ID."""
        raw_id = f"memory:{len(self.snapshots) + 1}"
        record = SnapshotRecord(
            id=raw_id,
            run_id=None,
            source_id=meta.source_id,
            via=meta.via,
            url=meta.url,
            final_url=meta.final_url,
            redirects=tuple(meta.redirects),
            http_status=meta.http_status,
            fetched_at=meta.fetched_at or utc_now(),
            headers=kept_headers(meta.headers),
            content_type=meta.content_type,
            filename=meta.filename,
            sha256="",
            size=len(body),
        )
        snapshot = record.with_body(body)
        self.snapshots[raw_id] = snapshot
        return snapshot

    def conditional_base(self, url: str) -> SnapshotRecord | None:
        """Never conditional."""
        return None

    def open(self, raw_id: str) -> Snapshot:
        """A kept snapshot."""
        return self.snapshots[raw_id]

    def message(
        self,
        level: MessageLevel,
        code: str,
        text: str,
        *,
        url: str | None = None,
        snapshot_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Keep the message."""
        self.messages.append((level, code, text))

    def count(self, key: str, n: int = 1) -> None:
        """Keep the counter."""
        self.counts[key] = self.counts.get(key, 0) + n
