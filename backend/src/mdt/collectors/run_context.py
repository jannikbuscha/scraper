"""The executing run (docs/COLLECTORS.md §2.1, §6): :class:`ActiveRun` is the
:class:`~mdt.collectors.base.RunContext` of its collector, the
:class:`~mdt.collectors.base.RunScope` of the domain layer and the
:class:`~mdt.collectors.fetchlog.RunHooks` of its client; :class:`Heartbeat` keeps the run
alive in the database and notices cancel requests written by other processes.

Messages and counters written while a domain function runs (inside its write unit) are
kept in memory and written when the function returns, because write units do not nest.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import httpx2
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from mdt.collectors.base import (
    MAX_KEY_CHARS,
    Candidate,
    Capture,
    Collector,
    MessageLevel,
    Observation,
    Outcome,
    Snapshot,
    TypeDeclaration,
)
from mdt.collectors.client import PoliteHttpClient, user_agent
from mdt.collectors.fetchlog import DatabaseSink
from mdt.collectors.sources import CollectorConfig
from mdt.collectors.store import SnapshotStore
from mdt.collectors.throttle import Clock, HostThrottle
from mdt.collectors.urls import UrlError, parse_fetch_url
from mdt.config import Settings, contact_email_problem
from mdt.db.models import CollectorRun as RunRow
from mdt.db.models import RunMessage, SourceObservation
from mdt.db.session import read_transaction, write_transaction
from mdt.domain import document_versions as documents_domain
from mdt.domain import observations as observations_domain
from mdt.domain import proposals as proposals_domain
from mdt.domain import reconcile as reconcile_domain
from mdt.domain.clock import utc_now
from mdt.domain.records import api_value, load_links, table_of
from mdt.domain.registry import ENTITY_TYPES

log = logging.getLogger("mdt.collectors")

#: Run message codes per level (docs/COLLECTORS.md §6.6).
MESSAGE_CODES: Mapping[str, frozenset[str]] = {
    "error": frozenset(
        {"fatal", "parse_error", "http_error", "blocked", "robots_unavailable", "write_error"}
    ),
    "warning": frozenset(
        {
            "throttled",
            "invalid_value",
            "unknown_code",
            "unmapped_label",
            "incomplete_candidate",
            "conflicting_candidates",
            "soft_404",
            "no_server_rendered_content",
            "unsupported_content",
            "checksum_mismatch",
            "ambiguous_time",
            "listing_changed",
        }
    ),
    "info": frozenset({"subject_deleted", "discarded", "listing_complete"}),
}
#: At most this many messages per run and code are stored (DATA_MODEL §14.4).
MAX_MESSAGES_PER_CODE = 200
MAX_MESSAGE_CHARS = 2000
#: The ``stats`` keys of DATA_MODEL §14.2 (all present, 0 by default) besides ``extra``.
STATS_KEYS = (
    "requests",
    "not_modified",
    "robots_disallowed",
    "bytes",
    "snapshots",
    "pages_parsed",
    "parse_errors",
    "items_seen",
    "entities_created",
    "entities_updated",
    "revisions",
    "proposals_opened",
    "proposals_seen_again",
    "proposals_superseded",
    "observations_new",
    "observations_missing",
    "links_suggested",
    "messages_suppressed",
    "errors",
    "warnings",
)
_STATS_KEY_SET = frozenset(STATS_KEYS)
STATS_FLUSH_EVERY = 20  # requests (docs/COLLECTORS.md §6.1)
HEARTBEAT_S = 30.0
CANCEL_POLL_S = 2.0

Progress = Callable[[Mapping[str, Any]], None]


def empty_stats() -> dict[str, Any]:
    """The initial ``stats`` of a run."""
    return {**dict.fromkeys(STATS_KEYS, 0), "extra": {}}


class ActiveRun:
    """One executing run (see the module docstring)."""

    def __init__(
        self,
        *,
        run_id: str,
        mode: str,
        params: Mapping[str, Any],
        implementation: Collector,
        config: CollectorConfig,
        settings: Settings,
        session: Session,
        cancel: threading.Event,
        transport: httpx2.BaseTransport | None,
        replay: bool,
        clock: Clock | None = None,
        throttle: HostThrottle | None = None,
        progress: Progress | None = None,
    ) -> None:
        self._run_id = run_id
        self._mode = mode
        self._params = dict(params)
        self.implementation = implementation
        self._config = config
        self._settings = settings
        self.session = session
        self.cancel = cancel
        self.progress = progress
        self.store = SnapshotStore(settings.raw_path)
        self.stats = empty_stats()
        # The collector's VERSION is bumped when parsing or mapping changes (§2.1).
        self.stats["extra"]["collector_version"] = implementation.VERSION
        self._stats_dirty = True
        self._memory: dict[str, Any] = {}
        self._codes: dict[str, int] = {}
        self._pending: list[dict[str, Any]] = []
        self._domain_depth = 0
        self._flushed_requests = 0
        self.complete = False
        self.reconciled = False
        email = None if contact_email_problem(settings.contact_email) else settings.contact_email
        self._client = PoliteHttpClient(
            config,
            DatabaseSink(session, self.store, run_id=run_id, hooks=self),
            user_agent=user_agent(email, settings.project_url),
            transport=transport,
            source_id=config.name,
            run_id=run_id,
            replay=replay,
            clock=clock,
            throttle=throttle,
            cancel=cancel,
        )

    # ----------------------------------------------------------------------------------
    # RunContext and RunScope properties
    # ----------------------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        """The run's ID."""
        return self._run_id

    @property
    def mode(self) -> str:
        """``incremental`` or ``full``."""
        return self._mode

    @property
    def params(self) -> Mapping[str, Any]:
        """The run parameters (docs/COLLECTORS.md §6.4)."""
        return self._params

    @property
    def options(self) -> Mapping[str, Any]:
        """The collector's options from ``sources.yaml``."""
        return self._config.options

    @property
    def client(self) -> PoliteHttpClient:
        """The run's polite client."""
        return self._client

    @property
    def settings(self) -> Settings:
        """The app settings the run executes with."""
        return self._settings

    @property
    def collector(self) -> str:
        """The collector's name."""
        return self._config.name

    @property
    def declaration(self) -> Mapping[str, TypeDeclaration]:
        """What the collector may do per entity type."""
        return self.implementation.DECLARATION

    @property
    def config(self) -> CollectorConfig:
        """The collector's effective settings."""
        return self._config

    @property
    def memory(self) -> dict[str, Any]:
        """Per-run state of the domain layer."""
        return self._memory

    # ----------------------------------------------------------------------------------
    # Writes through the domain layer
    # ----------------------------------------------------------------------------------

    def reconcile(self, candidate: Candidate) -> Outcome:
        """One write unit for one candidate (DATA_MODEL §15.11)."""
        if candidate.entity_type not in self.declaration:
            raise ValueError(f"{self.collector} declares no type {candidate.entity_type!r}")
        _check_key(candidate.key)
        self.count("items_seen")
        with self._domain_call():
            outcome = reconcile_domain.reconcile_candidate(self.session, self, candidate)
        self.reconciled = True
        return outcome

    def observe(
        self,
        entity_type: str,
        key: str,
        *,
        url: str | None = None,
        label: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """A sighting (DATA_MODEL §15.7)."""
        _check_key(key)
        self.count("items_seen")
        with self._domain_call():
            observations_domain.record_sighting(
                self.session, self, entity_type, key, url=url, label=label, details=details
            )

    def first_archived(self, subject_id: str, capture: Capture, *, exact: bool) -> Outcome:
        """C5: an archive upper bound (DATA_MODEL §15.12)."""
        with self._domain_call():
            outcome = reconcile_domain.record_first_archived(
                self.session, self, subject_id, capture, exact=exact
            )
        self.reconciled = True
        return outcome

    def tag_document(self, document_id: str) -> Outcome:
        """The built-in ``tagger``: tag one stored document (docs/COLLECTORS.md §8.6)."""
        with self._domain_call():
            return documents_domain.tag_document(self.session, self, document_id)

    def finish_steps(self, *, cancelled: bool) -> None:
        """The disappearance step after a complete listing of a run that was not cancelled,
        and the duplicate detection when the run reconciled anything (docs/COLLECTORS.md
        §6.1)."""
        if self.complete and not cancelled:
            with self._domain_call():
                observations_domain.disappearance_step(self.session, self)
        if self.reconciled:
            with self._domain_call():
                proposals_domain.detect_duplicates(self.session, self)

    @contextmanager
    def _domain_call(self) -> Iterator[None]:
        self._domain_depth += 1
        try:
            yield
        finally:
            self._domain_depth -= 1
            if self._domain_depth == 0:
                self.flush()

    # ----------------------------------------------------------------------------------
    # Messages, counters and the listing
    # ----------------------------------------------------------------------------------

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
        """A run message (docs/COLLECTORS.md §6.6); beyond 200 per code only
        ``stats.messages_suppressed`` grows."""
        if code not in MESSAGE_CODES.get(level, frozenset()):
            raise ValueError(f"unknown run message {level}/{code}")
        if level == "error":
            self.count("errors")
        elif level == "warning":
            self.count("warnings")
        if code == "parse_error":
            self.count("parse_errors")
        seen = self._codes.get(code, 0) + 1
        self._codes[code] = seen
        if seen > MAX_MESSAGES_PER_CODE:
            self.count("messages_suppressed")
            return
        self._pending.append(
            {
                "run_id": self.run_id,
                "at": utc_now(),
                "level": level,
                "code": code,
                "message": text[:MAX_MESSAGE_CHARS],
                "url": url,
                "raw_snapshot_id": snapshot_id,
                "subject_id": subject_id,
                "details": dict(details or {}),
            }
        )
        if self._domain_depth == 0:
            self.flush()

    def count(self, key: str, n: int = 1) -> None:
        """Add to a standard ``stats`` key or to ``stats.extra[key]``."""
        if key in _STATS_KEY_SET:
            self.stats[key] += n
            self._stats_dirty = True
        else:
            extra = self.stats["extra"]
            extra[key] = extra.get(key, 0) + n
            self._stats_dirty = True
        if key == "requests" and (
            self.stats["requests"] // STATS_FLUSH_EVERY
            > self._flushed_requests // STATS_FLUSH_EVERY
        ):
            self._flushed_requests = self.stats["requests"]
            if self._domain_depth == 0:
                self.flush()
            self._report_progress()
        elif key == "pages_parsed":
            self._report_progress()

    def listing_complete(self) -> None:
        """Every listing unit was parsed. A run with ``limit`` never sets it."""
        if self.complete or "limit" in self.params:
            return
        self.complete = True
        self._client.listing_done()
        with write_transaction(self.session):
            self.session.execute(
                update(RunRow).where(RunRow.id == self.run_id).values(complete_listing=True)
            )
        self.message(
            "info",
            "listing_complete",
            f"listing complete: {self.stats['items_seen']} items seen, "
            f"{self.stats['pages_parsed']} pages parsed",
            details={
                "items_seen": self.stats["items_seen"],
                "pages_parsed": self.stats["pages_parsed"],
            },
        )

    def cancelled(self) -> bool:
        """True once a cancel was requested."""
        return self.cancel.is_set()

    def flush(self) -> None:
        """Write pending messages and, if they changed, the stats (small write units)."""
        if not self._pending and not self._stats_dirty:
            return
        with write_transaction(self.session):
            if self._pending:
                self.session.execute(insert(RunMessage), self._pending)
                self._pending = []
            if self._stats_dirty:
                self.session.execute(
                    update(RunRow)
                    .where(RunRow.id == self.run_id, RunRow.status == "running")
                    .values(stats=_copy_stats(self.stats))
                )
                self._stats_dirty = False

    def _report_progress(self) -> None:
        if self.progress is not None:
            self.progress(_copy_stats(self.stats))

    # ----------------------------------------------------------------------------------
    # Read helpers (each in its own read transaction)
    # ----------------------------------------------------------------------------------

    def live_records(self, entity_type: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        """``{id, <field>: value}`` of every live record of the type, by ID."""
        spec = ENTITY_TYPES[entity_type]
        wanted = [spec.field(name) for name in fields]
        table = table_of(spec)
        with read_transaction(self.session):
            rows = [
                dict(row)
                for row in self.session.execute(
                    select(table).where(table.c.deleted_at.is_(None)).order_by(table.c.id)
                ).mappings()
            ]
            links = (
                load_links(self.session, [row["id"] for row in rows])
                if any(field.type == "doc_links" for field in wanted)
                else {}
            )
        return [
            {
                "id": row["id"],
                **{field.name: api_value(field, row, links.get(row["id"])) for field in wanted},
            }
            for row in rows
        ]

    def observation(self, key: str) -> Observation | None:
        """This collector's observation of ``key``."""
        with read_transaction(self.session):
            row = self.session.scalars(
                select(SourceObservation).where(
                    SourceObservation.collector == self.collector, SourceObservation.key == key
                )
            ).first()
            return None if row is None else observation_of(row)

    def latest_snapshot(self, url: str) -> Snapshot | None:
        """The newest stored response for the URL (any run)."""
        try:
            normalised = parse_fetch_url(url).url
        except UrlError:
            return None
        record = self.store.latest_for_url(self.session, normalised)
        if record is None:
            return None
        return record.with_body(self.store.read_body(record.sha256))


def observation_of(row: SourceObservation) -> Observation:
    """The interface object of an observation row."""
    return Observation(
        id=row.id,
        collector=row.collector,
        key=row.key,
        entity_type=row.entity_type,
        subject_id=row.subject_id,
        bound_by=row.bound_by,
        bound_at=row.bound_at,
        external_id=row.external_id,
        url=row.url,
        label=row.label,
        first_seen_at=row.first_seen_at,
        first_seen_run=row.first_seen_run,
        last_seen_at=row.last_seen_at,
        last_seen_run=row.last_seen_run,
        present=bool(row.present),
        missing_since_at=row.missing_since_at,
        missing_since_run=row.missing_since_run,
        missing_runs=row.missing_runs,
        last_snapshot_id=row.last_snapshot_id,
        details=dict(row.details or {}),
    )


def _check_key(key: str) -> None:
    if not key or len(key) > MAX_KEY_CHARS:
        raise ValueError(f"observation keys need 1 to {MAX_KEY_CHARS} characters")


def _copy_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    return {**stats, "extra": dict(stats["extra"])}


class Heartbeat:
    """Updates ``heartbeat_at`` every ``interval`` seconds and polls ``cancel_requested_at``
    every ``poll`` seconds (a cancel requested by another process), from its own thread
    and session (docs/COLLECTORS.md §6.3)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        run_id: str,
        cancel: threading.Event,
        *,
        interval: float = HEARTBEAT_S,
        poll: float = CANCEL_POLL_S,
    ) -> None:
        self.session_factory = session_factory
        self.run_id = run_id
        self.cancel = cancel
        self.interval = interval
        self.poll = poll
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"heartbeat-{run_id}", daemon=True)

    def start(self) -> None:
        """Start beating."""
        self._thread.start()

    def stop(self) -> None:
        """Stop and wait for the thread."""
        self._stop.set()
        self._thread.join(timeout=self.poll + 5)

    def _loop(self) -> None:
        last_beat = time.monotonic()
        with self.session_factory() as session:
            while not self._stop.wait(self.poll):
                try:
                    if time.monotonic() - last_beat >= self.interval:
                        last_beat = time.monotonic()
                        with write_transaction(session):
                            session.execute(
                                update(RunRow)
                                .where(RunRow.id == self.run_id, RunRow.status == "running")
                                .values(heartbeat_at=utc_now())
                            )
                    if not self.cancel.is_set():
                        with read_transaction(session):
                            requested = session.scalar(
                                select(RunRow.cancel_requested_at).where(RunRow.id == self.run_id)
                            )
                        if requested is not None:
                            self.cancel.set()
                except Exception:  # keep beating; the next round tries again
                    log.exception("heartbeat of run %s failed", self.run_id)
