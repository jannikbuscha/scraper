"""Shared helpers of the Phase 2 domain tests (synthetic values only).

* ``p2``: the test database with settings whose codebook also has a synthetic
  ``event_patterns.yaml`` (the tagger needs one), a session factory, and helpers to start
  runs, store snapshots and build candidates.
* :class:`StubScope` is a :class:`~mdt.collectors.base.RunScope` for calling the domain
  layer directly; it records messages and counters.
"""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from mdt.collectors.base import Candidate, Evidence, LinkHint, TypeDeclaration
from mdt.collectors.sources import CollectorConfig, parse_sources
from mdt.collectors.store import SnapshotMeta, SnapshotStore
from mdt.config import Settings
from mdt.db.models import CollectorRun, Proposal, Revision, SourceObservation
from mdt.db.session import create_session_factory, read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.clock import utc_now
from mdt.domain.ids import new_id
from mdt.domain.revisions import apply_change
from tests.conftest import Db, make_settings

#: Synthetic event patterns (lang ``lang_a`` is a code of the synthetic codebook).
PATTERNS = """\
version: 1
patterns:
  - {id: example_launch, event_type: launch, lang: lang_a, phrases: ["went live"]}
  - {id: example_pilot, event_type: beta_launch, lang: lang_a, stems: ["pilot"]}
"""

#: The declarations of the stub collector used by most tests.
PROJECTS_DECLARATION = TypeDeclaration(
    creates=False,
    writes=frozenset(
        {"name_uk", "description_uk", "ministry_categories", "ministry_urls", "official_urls"}
    ),
    propose_only=frozenset({"official_urls"}),
    match_rules=("external_id", "url_fields"),
    discontinued=True,
)
SERVICES_DECLARATION = TypeDeclaration(
    creates=True,
    writes=frozenset(
        {"project_id", "name_uk", "description_uk", "urls", "channels", "source_categories"}
    ),
    match_rules=("external_id", "url_fields"),
    discontinued=True,
)
DOCUMENTS_DECLARATION = TypeDeclaration(
    creates=True,
    writes=frozenset(
        {
            "title",
            "url",
            "publisher",
            "doc_type",
            "language",
            "published",
            "published_basis",
            "published_text",
            "published_at_utc",
            "source_record_at",
            "archive_urls",
        }
    ),
    match_rules=("document",),
)
DECLARATION: Mapping[str, TypeDeclaration] = {
    "project": PROJECTS_DECLARATION,
    "service": SERVICES_DECLARATION,
    "document": DOCUMENTS_DECLARATION,
}


def collector_config(name: str = "stub", **defaults: Any) -> CollectorConfig:
    """A collector configuration (``defaults`` e.g. ``discontinued_after_runs``)."""
    data = {"version": 1, "defaults": defaults, "collectors": {name: {"label": f"{name} label"}}}
    return parse_sources(data, Path("sources.yaml")).collectors[name]


@dataclass
class StubScope:
    """A run as the domain layer sees it, recording what the domain reports."""

    run_id: str
    collector: str = "stub"
    declaration: Mapping[str, TypeDeclaration] = field(default_factory=lambda: dict(DECLARATION))
    config: CollectorConfig = field(default_factory=collector_config)
    memory: dict[str, Any] = field(default_factory=dict)
    messages: list[tuple[str, str, str, dict[str, Any]]] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)

    def message(
        self,
        level: str,
        code: str,
        text: str,
        *,
        url: str | None = None,
        snapshot_id: str | None = None,
        subject_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        context = {"url": url, "snapshot_id": snapshot_id, "subject_id": subject_id}
        self.messages.append((level, code, text, {**context, **dict(details or {})}))

    def count(self, key: str, n: int = 1) -> None:
        self.counts[key] += n

    def codes(self) -> list[str]:
        """The message codes in order."""
        return [code for _, code, _, _ in self.messages]


@dataclass
class P2:
    """The Phase 2 test environment on one fresh database."""

    db: Db
    settings: Settings
    factory: sessionmaker[Session]

    def session(self) -> Session:
        return self.factory()

    def new_run(self, collector: str = "stub") -> str:
        """A finished collector run row (proposals and snapshots refer to runs)."""
        run_id = new_id("run")
        with self.session() as session, write_transaction(session):
            now = utc_now()
            session.execute(
                insert(CollectorRun).values(
                    id=run_id,
                    collector=collector,
                    trigger="cli",
                    mode="incremental",
                    params={},
                    status="succeeded",
                    started_at=now,
                    finished_at=now,
                    complete_listing=False,
                    stats={},
                    code_version="test",
                    config_hash="test",
                )
            )
        return run_id

    def scope(self, collector: str = "stub", **kwargs: Any) -> StubScope:
        """A scope on a new run of ``collector``."""
        return StubScope(run_id=self.new_run(collector), collector=collector, **kwargs)

    def snapshot(
        self,
        run_id: str | None,
        url: str = "https://example.org/page",
        body: bytes = b"<html>example</html>",
        fetched_at: str | None = None,
        source_id: str = "stub",
    ) -> str:
        """A stored raw snapshot (synthetic body)."""
        store = SnapshotStore(self.settings.raw_path)
        with self.session() as session:
            stored = store.put(
                session,
                body,
                SnapshotMeta(
                    source_id=source_id,
                    via="replay",
                    run_id=run_id,
                    url=url,
                    final_url=url,
                    http_status=200,
                    fetched_at=fetched_at,
                ),
            )
        return stored.raw_snapshot_id

    def count(self, model: type[Any], *conditions: Any) -> int:
        with self.session() as session, read_transaction(session):
            return int(
                session.execute(select(func.count()).select_from(model).where(*conditions)).scalar()
                or 0
            )

    def revisions(self) -> int:
        return self.count(Revision)

    def proposals(self, *conditions: Any) -> list[dict[str, Any]]:
        with self.session() as session, read_transaction(session):
            return [
                dict(row)
                for row in session.execute(
                    select(Proposal.__table__).where(*conditions).order_by(Proposal.created_at)
                ).mappings()
            ]

    def observation(self, collector: str, key: str) -> dict[str, Any] | None:
        with self.session() as session, read_transaction(session):
            row = (
                session.execute(
                    select(SourceObservation.__table__).where(
                        SourceObservation.collector == collector, SourceObservation.key == key
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row is not None else None

    def add_term(self, vocabulary: str, code: str) -> None:
        """Add an active synthetic term to a vocabulary (e.g. ``status:discontinued``)."""
        with self.session() as session:
            apply_change(
                session,
                "vocabulary_term",
                None,
                {"vocabulary": vocabulary, "code": code, "label_en": f"Example {code}"},
                Actor.ui(),
            )


@pytest.fixture(scope="session")
def p2_codebook(codebook_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic codebook plus synthetic event patterns."""
    target = tmp_path_factory.mktemp("codebook_p2")
    shutil.copytree(codebook_dir, target, dirs_exist_ok=True)
    (target / "event_patterns.yaml").write_text(PATTERNS, encoding="utf-8")
    return target


@pytest.fixture
def p2(db: Db, p2_codebook: Path, seed_dir: Path) -> Iterator[P2]:
    settings = make_settings(db.root, p2_codebook, seed_dir)
    yield P2(db, settings, create_session_factory(db.engine, settings))


def candidate(
    entity_type: str,
    key: str,
    snapshot_id: str,
    *,
    url: str | None = None,
    fields: Mapping[str, Any] | None = None,
    proposed: Mapping[str, Any] | None = None,
    external_id: str | None = None,
    label: str | None = None,
    text: str | None = None,
    extraction_method: str | None = None,
    links: list[LinkHint] | None = None,
    details: Mapping[str, Any] | None = None,
    field_snapshots: Mapping[str, list[str]] | None = None,
    source_url: str = "https://example.org/page",
) -> Candidate:
    """A candidate with synthetic values."""
    return Candidate(
        entity_type=entity_type,
        key=key,
        evidence=Evidence(raw_snapshot_id=snapshot_id, source_url=source_url),
        label=label,
        url=url,
        external_id=external_id,
        fields=dict(fields or {}),
        proposed=dict(proposed or {}),
        field_snapshots=dict(field_snapshots or {}),
        text=text,
        text_snapshot_id=snapshot_id if text is not None else None,
        extraction_method=extraction_method,
        links=list(links or []),
        details=dict(details or {}),
    )
