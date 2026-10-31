"""The interfaces where the framework and the collector modules meet (docs/COLLECTORS.md
§2.1), plus the view of a run that the domain layer gets (:class:`RunScope`).

Collectors build :class:`Candidate` objects from parsed snapshots and hand them to
:meth:`RunContext.reconcile`; everything that writes curated data happens behind that call
(docs/DATA_MODEL.md §15). Protocol members are read-only properties, so implementations
may use plain class or instance attributes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from mdt.collectors.client import PoliteHttpClient
    from mdt.collectors.sources import CollectorConfig
    from mdt.config import Settings

#: Longest quote a candidate or proposal carries (characters).
MAX_QUOTE_CHARS = 1000
#: Longest observation key (characters, DATA_MODEL §14.5).
MAX_KEY_CHARS = 500
#: Matching rules a declaration may name (DATA_MODEL §15.3), in the order they apply.
MATCH_RULES = ("external_id", "document", "url_fields")
#: Run modes (docs/COLLECTORS.md §6.4); collectors without the distinction treat both alike.
RUN_MODES = ("incremental", "full")

OutcomeAction = Literal["created", "updated", "unchanged", "proposed", "blocked", "observed"]
MessageLevel = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class Evidence:
    """Where a candidate was read."""

    raw_snapshot_id: str
    source_url: str
    quote: str | None = None  # verbatim, at most MAX_QUOTE_CHARS characters
    locator: str | None = None


@dataclass(frozen=True)
class LinkHint:
    """A link the source itself states (documents): a known record or an observation key
    of this collector, resolved through its binding."""

    snippet: str
    subject_id: str | None = None
    subject_key: str | None = None


@dataclass
class Candidate:
    """What a parser observed about one record (DATA_MODEL §15.1).

    ``fields`` holds observed values of the declared ``writes`` only and ``proposed`` those
    of the declared ``propose_only`` fields; a field that was not observed in this run is
    absent, never empty. ``field_evidence`` names, per field, where its value was read when
    that is not the main evidence (e.g. C1's official URLs: the project page, the link text
    as quote and the URL as locator); proposals of the field carry it.
    """

    entity_type: str  # project | service | document
    key: str  # observation key, stable per collector (at most MAX_KEY_CHARS characters)
    evidence: Evidence  # the main snapshot
    label: str | None = None
    url: str | None = None
    external_id: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    proposed: dict[str, Any] = field(default_factory=dict)
    field_snapshots: dict[str, list[str]] = field(default_factory=dict)
    field_evidence: dict[str, Evidence] = field(default_factory=dict)
    text: str | None = None  # documents: extracted text
    text_snapshot_id: str | None = None
    extraction_method: str | None = None
    links: list[LinkHint] = field(default_factory=list)  # documents
    details: dict[str, Any] = field(default_factory=dict)  # observation details

    def snapshots_of(self, name: str) -> list[str]:
        """The snapshots field ``name`` was parsed from (default: the main evidence's)."""
        return list(self.field_snapshots.get(name) or [self.evidence.raw_snapshot_id])

    def evidence_of(self, name: str) -> Evidence:
        """Where field ``name`` was read (default: the main evidence)."""
        return self.field_evidence.get(name, self.evidence)


@dataclass(frozen=True)
class TypeDeclaration:
    """What a collector may do with one entity type (DATA_MODEL §15.1)."""

    creates: bool  # unmatched: direct create (True) or create_entity proposal (False)
    writes: frozenset[str]
    propose_only: frozenset[str] = frozenset()
    match_rules: tuple[str, ...] = ()  # names from MATCH_RULES
    discontinued: bool = False


@dataclass(frozen=True)
class Outcome:
    """Result of one reconciled candidate or C5 capture."""

    action: OutcomeAction
    record_id: str | None = None
    proposal_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Capture:
    """The earliest Wayback capture of a URL (C5, DATA_MODEL §15.12)."""

    timestamp: str  # 14 digits, UTC
    original: str
    archive_url: str
    cdx_row: tuple[str, ...]  # the row as listed in the CDX response; json.dumps gives the quote
    request_url: str  # the CDX request URL (what C5 retrieved)
    raw_snapshot_id: str  # the CDX response
    fetched_at: str


@dataclass(frozen=True)
class Observation:
    """A ``source_observation`` row (DATA_MODEL §14.5)."""

    id: int
    collector: str
    key: str
    entity_type: str
    subject_id: str | None
    bound_by: str | None
    bound_at: str | None
    external_id: str | None
    url: str | None
    label: str | None
    first_seen_at: str
    first_seen_run: str
    last_seen_at: str
    last_seen_run: str
    present: bool
    missing_since_at: str | None
    missing_since_run: str | None
    missing_runs: int
    last_snapshot_id: str | None
    details: Mapping[str, Any]


@dataclass(frozen=True)
class Snapshot:
    """A stored response body with its metadata (DATA_MODEL §14.1): parser input."""

    raw_snapshot_id: str
    run_id: str | None
    source_id: str
    via: str
    url: str | None
    final_url: str | None
    redirects: tuple[str, ...]
    http_status: int | None
    fetched_at: str
    headers: Mapping[str, str]
    content_type: str | None
    filename: str | None
    sha256: str
    size: int
    body: bytes = field(repr=False)


class FatalRunError(Exception):
    """Stops the run as ``failed`` with this message as its ``error`` (docs/COLLECTORS.md
    §6.5), e.g. the listing host blocked before the listing was complete (§4.7)."""


class Collector(Protocol):
    """A collector module's ``COLLECTOR``.

    ``MODES`` lists the modes that make a difference (empty: none; both modes are still
    accepted and treated alike) and ``PARAMS`` the run parameters of §6.4 the collector
    supports; ``GET /api/collectors`` reports both (docs/API.md §7.2).
    """

    @property
    def NAME(self) -> str: ...

    @property
    def VERSION(self) -> int: ...  # bumped when parsing or mapping changes

    @property
    def DECLARATION(self) -> Mapping[str, TypeDeclaration]: ...

    @property
    def MODES(self) -> tuple[str, ...]: ...

    @property
    def PARAMS(self) -> frozenset[str]: ...

    def run(self, ctx: RunContext) -> None:
        """Discover, fetch, parse and reconcile, in a deterministic order."""
        ...


class RunContext(Protocol):
    """What a collector gets for one run (docs/COLLECTORS.md §2.1)."""

    @property
    def run_id(self) -> str: ...

    @property
    def mode(self) -> str: ...

    @property
    def params(self) -> Mapping[str, Any]: ...

    @property
    def options(self) -> Mapping[str, Any]: ...

    @property
    def client(self) -> PoliteHttpClient: ...

    @property
    def settings(self) -> Settings:
        """The app settings of the run (e.g. the codebook directory and the focal
        organisation's seed key)."""
        ...

    def reconcile(self, candidate: Candidate) -> Outcome:
        """One write unit for one candidate (DATA_MODEL §15.11)."""
        ...

    def observe(
        self,
        entity_type: str,
        key: str,
        *,
        url: str | None = None,
        label: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """A sighting: a key seen without being fetched (DATA_MODEL §15.7)."""
        ...

    def first_archived(self, subject_id: str, capture: Capture, *, exact: bool) -> Outcome:
        """C5: an archive upper bound for a project or service (DATA_MODEL §15.12)."""
        ...

    def tag_document(self, document_id: str) -> Outcome:
        """The built-in ``tagger``: one write unit that runs the tagger and the event
        patterns over a stored document's current text (docs/COLLECTORS.md §8.6)."""
        ...

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
        """A run message (docs/COLLECTORS.md §6.6)."""
        ...

    def listing_complete(self) -> None:
        """Every listing unit was parsed: sets ``complete_listing`` (§8 per collector)."""
        ...

    def cancelled(self) -> bool:
        """True once a cancel was requested; checked before every request and item."""
        ...

    def count(self, key: str, n: int = 1) -> None:
        """Add to a counter: a standard ``stats`` key (e.g. ``pages_parsed``) or, for any
        other name, ``stats.extra[key]``."""
        ...

    def live_records(self, entity_type: str, fields: Sequence[str]) -> list[dict[str, Any]]:
        """``{id, <field>: value}`` of every live record of the type (API representation)."""
        ...

    def observation(self, key: str) -> Observation | None:
        """This collector's observation of ``key``."""
        ...

    def latest_snapshot(self, url: str) -> Snapshot | None:
        """The newest stored response for the URL (any run)."""
        ...


def focal_org_id(ctx: RunContext) -> str | None:
    """The ID of the live focal organisation (``seed_key`` = the setting
    ``FOCAL_ORG_SEED_KEY``, DATA_MODEL §3.5), or None while it is not seeded: the
    ``publisher_org_id`` of the ministry's own pages (docs/COLLECTORS.md §8)."""
    key = ctx.settings.focal_org_seed_key
    for record in ctx.live_records("organization", ["seed_key"]):
        if record["seed_key"] == key:
            return str(record["id"])
    return None


class RunScope(Protocol):
    """The run as the domain layer sees it (reconciler, observations, proposals).

    ``memory`` is per-run state that the domain layer keeps between calls of the same run
    (e.g. the records already reconciled, DATA_MODEL §15.6, and those created or with a
    changed text, for the duplicate detection).
    """

    @property
    def run_id(self) -> str: ...

    @property
    def collector(self) -> str: ...

    @property
    def declaration(self) -> Mapping[str, TypeDeclaration]: ...

    @property
    def config(self) -> CollectorConfig: ...

    @property
    def memory(self) -> dict[str, Any]: ...

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
        """A run message (docs/COLLECTORS.md §6.6)."""
        ...

    def count(self, key: str, n: int = 1) -> None:
        """Add to a ``stats`` counter (see :meth:`RunContext.count`)."""
        ...
