"""The C5 test setup of docs/COLLECTORS.md §12.1 (synthetic values only).

* a test sources file: the repository's ``sources.yaml`` with ``wayback.options.prefixes`` =
  ``["example.org/projects/"]`` (:func:`use_test_sources`);
* synthetic projects and services with ``example.org`` and ``example.com`` URLs, created
  through ``apply_change`` (:func:`create_subjects`).

The CDX responses for exactly these URLs are the synthetic fixtures in
``backend/tests/fixtures/wayback/`` (their meta ``url`` is the query C5 builds); nothing here
describes a real site.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mdt.config import REPO_ROOT
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change
from tests.collectors.acceptance import Acceptance

TEST_PREFIX = "example.org/projects/"
SCOPE_NOTE = "Synthetic test project (example.org), not part of the dataset"
#: Synthetic projects by slug: ministry and official URLs.
PROJECTS: dict[str, dict[str, Any]] = {
    "example-alpha": {
        "name_en": "Example project Alpha",
        "ministry_urls": ["https://example.org/projects/technologies/example-alpha"],
        "official_urls": ["https://example.com/"],
    },
    "example-beta": {
        "name_en": "Example project Beta",
        "ministry_urls": ["https://example.org/projects/business/example-beta"],
        "official_urls": ["https://www.example.org/"],
    },
    "example-gamma": {
        "name_en": "Example project Gamma",
        "ministry_urls": ["https://example.org/projects/technologies/example-gamma"],
        "official_urls": ["https://example.org/about"],
    },
}
#: Synthetic services (all under ``example-alpha``) by name: their URLs.
SERVICES: dict[str, list[str]] = {
    "Example service One": ["https://example.org/services/example-one"],
    "Example service Two": ["https://example.org/services/example-two"],
}


def write_test_sources(directory: Path) -> Path:
    """Write the test sources file into ``directory`` and return its path."""
    data = yaml.safe_load((REPO_ROOT / "sources.yaml").read_text("utf-8"))
    data["collectors"]["wayback"]["options"]["prefixes"] = [TEST_PREFIX]
    path = directory / "sources.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")
    return path


def use_test_sources(acceptance: Acceptance) -> None:
    """Point the test database's settings (``SOURCES_FILE``) at the test sources file."""
    path = write_test_sources(acceptance.db.root)
    acceptance.db.settings = acceptance.settings.model_copy(update={"sources_file": path})


def create_subjects(acceptance: Acceptance) -> dict[str, str]:
    """Create the synthetic projects and services; returns slug or name → ID."""
    ids: dict[str, str] = {}
    with acceptance.db.session() as session:
        for slug, values in PROJECTS.items():
            changes = {"slug": slug, "scope_note": SCOPE_NOTE, **values}
            ids[slug] = apply_change(session, "project", None, changes, Actor.ui()).entity_id
        for name, urls in SERVICES.items():
            changes = {"project_id": ids["example-alpha"], "name_en": name, "urls": urls}
            ids[name] = apply_change(session, "service", None, changes, Actor.ui()).entity_id
    return ids


def setup(acceptance: Acceptance) -> None:
    """The whole C5 setup: test sources file and synthetic subjects."""
    use_test_sources(acceptance)
    create_subjects(acceptance)
