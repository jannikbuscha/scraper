"""Definition of Done 3: a complete collector run is idempotent (docs/COLLECTORS.md §12.1,
docs/DATA_MODEL.md §15.6).

On a fresh database (``alembic upgrade head`` + ``mdt seed`` with the real codebook and
seed), each case runs its collector twice against the same fixtures (the replay transport;
nothing reaches the network). After the second run there is no new record of any type, no
new revision, no new proposal row, no proposal that changed its state, no new
``document_text`` row, and the document links are identical; the observations of the keys
the first run saw show the second run as their last sighting. Both runs are listed by
``GET /api/runs`` with their stats, and URLs without a fixture make the runs ``partial``
with their ``refused`` fetches and error messages visible through the API ("runs and
errors are visible in the UI").

**Adding a collector:** append an :class:`IdempotencyCase` to :data:`CASES` (a ``setup``
callable prepares the database before the first run, e.g. synthetic records for C5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import select

from mdt.db.models import Project
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change
from tests.collectors import wayback_helpers
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template

__all__ = ["acceptance", "acceptance_template"]


@dataclass(frozen=True)
class IdempotencyCase:
    """One collector run twice against one fixture set."""

    collector: str
    fixtures: str | tuple[str, ...]
    mode: str = "incremental"
    params: Mapping[str, Any] = field(default_factory=dict)
    #: Prepares the database before the first run.
    setup: Callable[[Acceptance], None] | None = None
    #: The first run must create at least these records (type → count).
    creates_at_least: Mapping[str, int] = field(default_factory=dict)
    #: Distinguishes cases of the same collector and mode in the pytest ID.
    variant: str = ""

    @property
    def id(self) -> str:
        """The pytest ID of the case."""
        return "-".join(part for part in (self.collector, self.mode, self.variant) if part)


def _unmatched_brave1(acceptance: Acceptance) -> None:
    """Clear the ministry URL of the seed project ``brave1``, so that its listing entry is
    unmatched: run 1 proposes it (``create_entity``) and creates its project page, whose
    key shares the entry's external_id (DATA_MODEL §15.3)."""
    with acceptance.db.session() as session:
        project_id = session.scalar(select(Project.id).where(Project.slug == "brave1"))
        assert project_id is not None
        apply_change(session, "project", project_id, {"ministry_urls": []}, Actor.ui())


CASES: list[IdempotencyCase] = [
    IdempotencyCase("ministry_projects", "ministry_projects", creates_at_least={"document": 4}),
    IdempotencyCase(
        "ministry_projects",
        "ministry_projects",
        setup=_unmatched_brave1,
        creates_at_least={"document": 4},
        variant="unmatched-entry",
    ),
    IdempotencyCase("ministry_news", "ministry_news", creates_at_least={"document": 50}),
    IdempotencyCase(
        "ministry_news", "ministry_news", mode="full", creates_at_least={"document": 50}
    ),
    IdempotencyCase("diia_catalog", "diia_catalog", creates_at_least={"service": 3, "document": 3}),
    IdempotencyCase("project_sites", "project_sites", creates_at_least={"document": 3}),
    IdempotencyCase("kmu_news", "kmu_news", creates_at_least={"document": 5}),
    # C5: the test sources file and synthetic subjects of docs/COLLECTORS.md §12.1.
    IdempotencyCase(
        "wayback",
        "wayback",
        setup=wayback_helpers.setup,
        creates_at_least={"event": 5, "evidence": 5},
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_a_second_run_writes_nothing_new(acceptance: Acceptance, case: IdempotencyCase) -> None:
    if case.setup is not None:
        case.setup(acceptance)
    before = acceptance.state()
    first = acceptance.run(case.collector, case.fixtures, mode=case.mode, params=case.params)
    after_first = acceptance.state()
    seen_first = {
        key
        for key, observation in acceptance.observations(case.collector).items()
        if observation["last_seen_run"] == first
    }
    assert seen_first
    for entity_type, count in case.creates_at_least.items():
        assert after_first.records[entity_type] - before.records[entity_type] >= count
    second = acceptance.run(case.collector, case.fixtures, mode=case.mode, params=case.params)
    after_second = acceptance.state()

    assert after_second.records == after_first.records
    assert after_second.revisions == after_first.revisions
    assert after_second.proposals == after_first.proposals  # no new row, no state change
    assert after_second.texts == after_first.texts
    assert after_second.links == after_first.links
    stats = acceptance.run_row(second)["stats"]
    assert (stats["entities_created"], stats["entities_updated"], stats["revisions"]) == (0, 0, 0)
    assert stats["proposals_opened"] == 0 and stats["proposals_superseded"] == 0

    observations = acceptance.observations(case.collector)
    assert {key for key in seen_first if observations[key]["last_seen_run"] == second} == (
        seen_first
    )
    _runs_and_errors_are_visible(acceptance, case, first, second)


def _runs_and_errors_are_visible(
    acceptance: Acceptance, case: IdempotencyCase, first: str, second: str
) -> None:
    """Both runs are listed with their stats; a run with refused URLs (no fixture) is
    ``partial`` and its refused fetches and error messages are served by the API."""
    with acceptance.api() as client:
        response = client.get("/api/runs", params={"collector": case.collector})
        assert response.status_code == 200
        runs = {run["id"]: run for run in response.json()["items"]}
        assert {first, second} <= set(runs)
        for run_id in (first, second):
            run = runs[run_id]
            assert run["stats"]["requests"] > 0 and run["stats"]["pages_parsed"] > 0
            refused = client.get(f"/api/runs/{run_id}/fetches", params={"outcome": "refused"})
            assert refused.status_code == 200
            errors = client.get(f"/api/runs/{run_id}/messages", params={"level": "error"})
            assert errors.status_code == 200
            if refused.json()["total"]:
                assert run["status"] == "partial"
                assert all(item["error"] == "no fixture" for item in refused.json()["items"])
                assert errors.json()["total"] > 0
            else:
                assert run["status"] in ("succeeded", "partial")


def test_a_second_tagger_run_writes_nothing_new(acceptance: Acceptance) -> None:
    """The built-in ``tagger`` over documents created by a C4 run plus one manual document
    whose synthetic text names a seed project (docs/COLLECTORS.md §8.6, §12.1): the first run
    adds the manual document's suggested link (the C4 documents were tagged when they were
    created); the second run writes nothing."""
    acceptance.run("ministry_news", "ministry_news")
    document_id = _manual_document(acceptance)
    before = acceptance.state()

    first = acceptance.run("tagger", "ministry_news")
    after_first = acceptance.state()
    run = acceptance.run_row(first)
    assert run["status"] == "succeeded" and not run["complete_listing"]
    assert run["stats"]["links_suggested"] >= 1 and run["stats"]["revisions"] >= 1
    assert run["stats"]["extra"]["collector_version"] == 1
    assert any(
        subject.startswith("prj_") and (origin, state) == ("auto", "suggested")
        for subject, origin, state in after_first.links[document_id]
    )
    assert after_first.revisions > before.revisions
    assert not acceptance.observations("tagger")

    second = acceptance.run("tagger", "ministry_news")
    after_second = acceptance.state()
    assert after_second == after_first
    stats = acceptance.run_row(second)["stats"]
    assert (stats["entities_updated"], stats["revisions"], stats["proposals_opened"]) == (0, 0, 0)


def _manual_document(acceptance: Acceptance) -> str:
    """A manual document from an uploaded synthetic HTML file that names the seed project
    ``Дія`` (its name is an alias of kind ``name``) next to a launch phrase."""
    html = (
        "<html><head><title>Example note</title></head><body>"
        "<p>Example note written for the tagger test.</p>"
        "<p>Дія запустили приклад для тесту.</p></body></html>"
    )
    with acceptance.api() as client:
        upload = client.post(
            "/api/uploads", params={"filename": "example-note.html"}, content=html.encode()
        )
        assert upload.status_code == 201, upload.text
        created = client.post(
            "/api/documents/manual",
            json={
                "snapshot_id": upload.json()["upload"]["id"],
                "title": "Example note",
                "doc_type": "other",
                "language": "uk",
            },
        )
        assert created.status_code == 201, created.text
        return str(created.json()["item"]["id"])
