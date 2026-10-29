"""Field filters of the list query (docs/API.md §4.1) on a shared synthetic catalog."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from mdt.db.session import write_transaction
from mdt.domain.comments import create_comment, delete_comment, resolve_comment
from mdt.domain.query import list_entities
from mdt.domain.revisions import soft_delete
from tests.conftest import Db
from tests.helpers import USER, create_event, create_project, create_service
from tests.read_helpers import (
    assert_consistent,
    create,
    create_document,
    ids_of,
    open_copy,
)


@dataclass
class Catalog:
    db: Db
    ids: dict[str, str]

    def found(self, entity_type: str, params: dict[str, str]) -> set[str]:
        with self.db.session() as session:
            result = list_entities(session, entity_type, {**params, "page_size": "500"})
        names = {entity_id: name for name, entity_id in self.ids.items()}
        return {names.get(entity_id, entity_id) for entity_id in ids_of(result)}


def build(session: Any) -> dict[str, str]:
    ids: dict[str, str] = {}
    ids["ALPHA"] = create_project(
        session,
        slug="alpha",
        name_en="Alpha",
        name_uk="Альфа",
        status="active",
        paper_cluster="cluster_a",
        policy_domains=["domain_b", "domain_a"],
        official_urls=["https://example.org/alpha"],
        aliases=[{"text": "Дія Example", "lang": "uk"}],
        in_paper_scope=True,
        scope_note="In scope for the example.",
        description_en="З'явилася послуга",
    ).entity_id
    ids["BETA"] = create_project(
        session,
        slug="beta",
        name_en=None,
        name_uk="Бета",
        status="planned",
        paper_cluster="cluster_b",
        policy_domains=["domain_c"],
    ).entity_id
    ids["GAMMA"] = create_project(session, slug="gamma", name_en="Gamma 100%").entity_id
    deleted = create_project(session, slug="deleted-project", name_en="Deleted project")
    soft_delete(session, "project", deleted.entity_id, USER)
    ids["DELETED"] = deleted.entity_id

    ids["S_ALPHA"] = create_service(session, ids["ALPHA"], name_en="Alpha service").entity_id
    ids["S_CHILD"] = create_service(
        session, ids["ALPHA"], name_en="Alpha child", parent_service_id=ids["S_ALPHA"]
    ).entity_id
    ids["S_BETA"] = create_service(session, ids["BETA"], name_en="Beta service").entity_id

    ids["E1"] = create_event(session, ids["ALPHA"], "launch", "2012-05").entity_id
    ids["E2"] = create_event(session, ids["BETA"], "launch", "2016").entity_id
    ids["E3"] = create_event(session, ids["GAMMA"], "expansion", "2016-03-10").entity_id
    ids["E4"] = create_event(session, ids["GAMMA"], "announced").entity_id
    ids["E5"] = create_event(session, ids["BETA"], "rebrand", "2016-Q1").entity_id
    ids["E6"] = create_event(session, ids["S_ALPHA"], "first_archived", "2013-02-03").entity_id

    def link(subject: str, state: str) -> dict[str, str]:
        return {"subject_id": ids[subject], "state": state}

    ids["D1"] = create_document(
        session,
        "Example report",
        url="https://example.org/report",
        retrieved_at="2024-03-05T23:30:00Z",
        links=[link("ALPHA", "confirmed"), link("S_BETA", "suggested")],
    ).entity_id
    ids["D2"] = create_document(
        session,
        "Second document",
        retrieved_at="2024-03-06T00:30:00+00:00",
        links=[link("ALPHA", "rejected")],
    ).entity_id
    ids["D3"] = create_document(session, "Third document").entity_id
    ids["D4"] = create_document(
        session, "Fourth document", links=[link("S_ALPHA", "confirmed")]
    ).entity_id
    ids["D5"] = create_document(
        session, "Fifth document", links=[link("ALPHA", "suggested")]
    ).entity_id

    ids["R1"] = create(
        session, "relation", from_id=ids["ALPHA"], to_id=ids["S_BETA"], relation_type="relates_a"
    ).entity_id
    ids["R2"] = create(
        session, "relation", from_id=ids["BETA"], to_id=ids["ALPHA"], relation_type="relates_b"
    ).entity_id

    ids["I1"] = create(
        session, "indicator", subject_id=ids["ALPHA"], metric="Users", value=15, unit="people"
    ).entity_id
    ids["I2"] = create(
        session, "indicator", subject_id=ids["BETA"], metric="Budget", value=-2.5
    ).entity_id
    ids["I3"] = create(
        session, "indicator", subject_id=ids["GAMMA"], metric="Count", value=3
    ).entity_id

    create_comment(session, ids["ALPHA"], "On the name", USER, field="name_en")
    root = create_comment(session, ids["ALPHA"], "Entity-level thread", USER)
    create_comment(session, ids["ALPHA"], "A reply", USER, parent_id=root.entity_id)
    resolved = create_comment(session, ids["ALPHA"], "Resolved thread", USER)
    resolve_comment(session, resolved.entity_id, USER)
    gone = create_comment(session, ids["BETA"], "Deleted thread", USER)
    delete_comment(session, gone.entity_id, USER)
    return ids


@pytest.fixture(scope="module")
def catalog(
    tmp_path_factory: pytest.TempPathFactory, template_db: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Catalog]:
    database = open_copy(tmp_path_factory, template_db, codebook_dir, seed_dir, "filters")
    try:
        with database.session() as session:
            ids = build(session)
        yield Catalog(database, ids)
        assert_consistent(database)
    finally:
        database.engine.dispose()


EVENTS = {"E1", "E2", "E3", "E4", "E5", "E6"}
DOCUMENTS = {"D1", "D2", "D3", "D4", "D5"}

CASES: list[tuple[str, dict[str, str], set[str]]] = [
    # text: literal, case-insensitive substring incl. Cyrillic; never NULL
    ("project", {"f.name_uk": "contains:АЛЬ"}, {"ALPHA"}),
    ("project", {"f.name_en": "contains:ALPHA"}, {"ALPHA"}),
    ("project", {"f.name_en": "contains:%"}, {"GAMMA"}),
    ("project", {"f.name_en": "contains:_"}, set()),
    ("project", {"f.name_en": "contains:"}, {"ALPHA", "GAMMA"}),
    ("project", {"f.name_en": "eq:alpha"}, {"ALPHA"}),
    ("project", {"f.name_en": "eq:alp"}, set()),
    ("project", {"f.name_en": "empty:true"}, {"BETA"}),
    ("project", {"f.name_en": "empty:false"}, {"ALPHA", "GAMMA"}),
    ("project", {"f.official_urls": "contains:example.org/ALPHA"}, {"ALPHA"}),
    ("project", {"f.official_urls": "empty:true"}, {"BETA", "GAMMA"}),
    ("project", {"f.aliases": "contains:дія"}, {"ALPHA"}),
    ("project", {"f.aliases": "eq:ДІЯ example"}, {"ALPHA"}),
    ("project", {"f.aliases": "eq:дія"}, set()),
    ("project", {"f.aliases": "empty:true"}, {"BETA", "GAMMA"}),
    ("project", {"f.description_en": "contains:з\u2019явилася"}, {"ALPHA"}),
    ("project", {"f.description_en": "contains:З\u02bcЯВ"}, {"ALPHA"}),
    ("project", {"f.created_by": "eq:USER"}, {"ALPHA", "BETA", "GAMMA"}),
    ("project", {"f.slug": "contains:ta"}, {"BETA"}),
    ("document", {"f.url": "contains:/report"}, {"D1"}),
    ("document", {"f.canonical_url": "eq:https://example.org/report"}, {"D1"}),
    # vocab: in / nin (NULL included) / empty / ~empty
    ("project", {"f.status": "in:active"}, {"ALPHA"}),
    ("project", {"f.status": "in:active,planned"}, {"ALPHA", "BETA"}),
    ("project", {"f.status": "in:active,~empty"}, {"ALPHA", "GAMMA"}),
    ("project", {"f.status": "in:~empty"}, {"GAMMA"}),
    ("project", {"f.status": "nin:active"}, {"BETA", "GAMMA"}),
    ("project", {"f.status": "nin:active,~empty"}, {"BETA"}),
    ("project", {"f.status": "nin:~empty"}, {"ALPHA", "BETA"}),
    ("project", {"f.status": "empty:true"}, {"GAMMA"}),
    ("project", {"f.status": "empty:false"}, {"ALPHA", "BETA"}),
    ("project", {"f.status": "in:no_such_code"}, set()),
    ("project", {"f.verification_status": "in:unverified"}, {"ALPHA", "BETA", "GAMMA"}),
    # derived vocab: a missing row counts as unknown, never empty
    ("project", {"f.period": "in:pre_invasion"}, {"ALPHA"}),
    ("project", {"f.period": "in:unknown"}, {"BETA", "GAMMA"}),
    ("project", {"f.period": "nin:unknown"}, {"ALPHA"}),
    ("project", {"f.period": "empty:true"}, set()),
    ("project", {"f.war_trajectory": "in:prewar_unchanged"}, {"ALPHA"}),
    ("service", {"f.period": "in:pre_ministry,unknown"}, {"S_ALPHA", "S_CHILD", "S_BETA"}),
    # vocab_list: any / all / none (empty lists included) / empty
    ("project", {"f.policy_domains": "any:domain_a"}, {"ALPHA"}),
    ("project", {"f.policy_domains": "any:domain_a,domain_c"}, {"ALPHA", "BETA"}),
    ("project", {"f.policy_domains": "any:domain_c,~empty"}, {"BETA", "GAMMA"}),
    ("project", {"f.policy_domains": "all:domain_a,domain_b"}, {"ALPHA"}),
    ("project", {"f.policy_domains": "all:domain_a,domain_c"}, set()),
    ("project", {"f.policy_domains": "none:domain_a"}, {"BETA", "GAMMA"}),
    ("project", {"f.policy_domains": "none:domain_a,~empty"}, {"BETA"}),
    ("project", {"f.policy_domains": "none:~empty"}, {"ALPHA", "BETA"}),
    ("project", {"f.policy_domains": "empty:true"}, {"GAMMA"}),
    ("project", {"f.policy_domains": "empty:false"}, {"ALPHA", "BETA"}),
    # bool, including the virtual scope fields
    ("project", {"f.in_paper_scope": "eq:true"}, {"ALPHA"}),
    ("project", {"f.in_paper_scope": "eq:false"}, {"BETA", "GAMMA"}),
    ("service", {"f.project_in_paper_scope": "eq:true"}, {"S_ALPHA", "S_CHILD"}),
    ("service", {"f.project_in_paper_scope": "eq:false"}, {"S_BETA"}),
    ("event", {"f.subject_in_paper_scope": "eq:true"}, {"E1", "E6"}),
    ("event", {"f.subject_in_paper_scope": "eq:false"}, {"E2", "E3", "E4", "E5"}),
    ("document", {"f.linked_in_paper_scope": "eq:true"}, {"D1", "D4"}),
    ("document", {"f.linked_in_paper_scope": "eq:false"}, {"D2", "D3", "D5"}),
    # partial dates: overlaps / within with open bounds and precision intervals
    ("event", {"f.date": "overlaps:2016-03-01..2016-03-31"}, {"E2", "E3", "E5"}),
    ("event", {"f.date": "within:2016-01-01..2016-03-31"}, {"E3", "E5"}),
    ("event", {"f.date": "within:2016-03-10.."}, {"E3"}),
    ("event", {"f.date": "overlaps:..2012-05-01"}, {"E1"}),
    ("event", {"f.date": "overlaps:2012-05-31..2012-05-31"}, {"E1"}),
    ("event", {"f.date": "within:2012-05-01..2012-05-31"}, {"E1"}),
    ("event", {"f.date": "within:2012-05-01..2012-05-30"}, set()),
    ("event", {"f.date": "overlaps:.."}, EVENTS - {"E4"}),
    ("event", {"f.date": "empty:true"}, {"E4"}),
    ("event", {"f.date": "empty:false"}, EVENTS - {"E4"}),
    # derived dates
    ("project", {"f.launch": "within:2012-01-01..2012-12-31"}, {"ALPHA"}),
    ("project", {"f.launch": "overlaps:2016-06-01..2016-06-30"}, {"BETA"}),
    ("project", {"f.launch": "empty:true"}, {"GAMMA"}),
    ("service", {"f.existed_by": "within:2013-01-01..2013-12-31"}, {"S_ALPHA"}),
    ("service", {"f.existed_by": "overlaps:2013-02-04.."}, set()),
    ("service", {"f.existed_by": "empty:false"}, {"S_ALPHA"}),
    # datetimes use their UTC calendar date
    ("document", {"f.retrieved_at": "within:2024-03-05..2024-03-05"}, {"D1"}),
    ("document", {"f.retrieved_at": "overlaps:2024-03-06.."}, {"D2"}),
    ("document", {"f.retrieved_at": "within:..2024-03-06"}, {"D1", "D2"}),
    ("document", {"f.retrieved_at": "empty:true"}, {"D3", "D4", "D5"}),
    ("document", {"f.retrieved_at": "overlaps:..9999-12-31"}, {"D1", "D2"}),
    # number ranges, including virtual counts
    ("project", {"f.open_comments": "range:1.."}, {"ALPHA"}),
    ("project", {"f.open_comments": "eq:2"}, {"ALPHA"}),
    ("project", {"f.open_comments": "eq:0"}, {"BETA", "GAMMA"}),
    ("project", {"f.comment_count": "eq:4"}, {"ALPHA"}),
    ("project", {"f.comment_count": "range:..0"}, {"BETA", "GAMMA"}),
    ("indicator", {"f.value": "range:10..20"}, {"I1"}),
    ("indicator", {"f.value": "range:..0"}, {"I2"}),
    ("indicator", {"f.value": "eq:3"}, {"I3"}),
    ("indicator", {"f.value": "eq:-2.5"}, {"I2"}),
    ("indicator", {"f.value": "range:-2.5..3"}, {"I2", "I3"}),
    ("indicator", {"f.value": "range:.."}, {"I1", "I2", "I3"}),
    # references, including ~empty
    ("service", {"f.parent_service_id": "in:~empty"}, {"S_ALPHA", "S_BETA"}),
    ("service", {"f.parent_service_id": "empty:false"}, {"S_CHILD"}),
    # document links: in = suggested or confirmed, confirmed only confirmed
    ("document", {"f.links": "confirmed:@ALPHA"}, {"D1"}),
    ("document", {"f.links": "in:@ALPHA"}, {"D1", "D5"}),
    ("document", {"f.links": "in:@S_BETA"}, {"D1"}),
    ("document", {"f.links": "confirmed:@S_BETA"}, set()),
    ("document", {"f.links": "in:@ALPHA,~empty"}, {"D1", "D3", "D5"}),
    ("document", {"f.links": "empty:true"}, {"D3"}),
    ("document", {"f.links": "empty:false"}, {"D1", "D2", "D4", "D5"}),
    # relation endpoint: from_id OR to_id
    ("relation", {"f.endpoint": "in:@ALPHA"}, {"R1", "R2"}),
    ("relation", {"f.endpoint": "in:@S_BETA"}, {"R1"}),
    ("relation", {"f.endpoint": "empty:true"}, set()),
    ("service", {"f.project_id": "in:@ALPHA"}, {"S_ALPHA", "S_CHILD"}),
    ("service", {"f.project_id": "in:@ALPHA,@BETA"}, {"S_ALPHA", "S_CHILD", "S_BETA"}),
    ("service", {"f.parent_service_id": "in:@S_ALPHA"}, {"S_CHILD"}),
    ("service", {"f.parent_service_id": "in:@S_ALPHA,~empty"}, {"S_ALPHA", "S_CHILD", "S_BETA"}),
    ("event", {"f.subject_id": "in:@S_ALPHA"}, {"E6"}),
    # filters combine with AND, and with q
    ("project", {"f.status": "nin:planned", "f.in_paper_scope": "eq:false"}, {"GAMMA"}),
    ("service", {"q": "alpha", "f.parent_service_id": "empty:true"}, {"S_ALPHA"}),
    # deletion state and the deleted_at system field
    ("project", {"deleted": "only"}, {"DELETED"}),
    ("project", {"deleted": "include", "f.deleted_at": "empty:false"}, {"DELETED"}),
    ("project", {"f.deleted_at": "empty:false"}, set()),
]


def _resolve(params: dict[str, str], ids: dict[str, str]) -> dict[str, str]:
    """Replace ``@NAME`` placeholders with catalog IDs."""
    resolved = {}
    for key, value in params.items():
        for name, entity_id in sorted(ids.items(), key=lambda pair: -len(pair[0])):
            value = value.replace(f"@{name}", entity_id)
        resolved[key] = value
    return resolved


@pytest.mark.parametrize(("entity_type", "params", "expected"), CASES)
def test_filter(
    catalog: Catalog, entity_type: str, params: dict[str, str], expected: set[str]
) -> None:
    assert catalog.found(entity_type, _resolve(params, catalog.ids)) == expected


def test_all_documents_without_filters(catalog: Catalog) -> None:
    assert catalog.found("document", {}) == DOCUMENTS


def test_created_at_filters_compare_the_utc_calendar_date(catalog: Catalog) -> None:
    with catalog.db.session() as session:
        result = list_entities(session, "project", {"f.slug": "eq:alpha"})
    created = date.fromisoformat(result["items"][0]["created_at"][:10])
    day = created.isoformat()
    next_day = (created + timedelta(days=1)).isoformat()
    previous_day = (created - timedelta(days=1)).isoformat()
    assert "ALPHA" in catalog.found("project", {"f.created_at": f"within:{day}..{day}"})
    assert catalog.found("project", {"f.created_at": f"overlaps:{next_day}.."}) == set()
    assert catalog.found("project", {"f.updated_at": f"within:..{previous_day}"}) == set()


def test_missing_derived_row_counts_as_unknown(db: Db) -> None:
    db.check_on_teardown = False  # the derived row is removed on purpose
    with db.session() as session:
        project = create_project(session, name_en="Without derived row")
        create_event(session, project.entity_id, "launch", "2012-05")
        with write_transaction(session):
            session.execute(
                text("DELETE FROM derived WHERE entity_id = :id"), {"id": project.entity_id}
            )
        unknown = list_entities(session, "project", {"f.period": "in:unknown"})
        assert ids_of(unknown) == [project.entity_id]
        assert ids_of(list_entities(session, "project", {"f.launch": "empty:true"})) == [
            project.entity_id
        ]
        sorted_ = list_entities(session, "project", {"sort": "-period,war_trajectory"})
        item = sorted_["items"][0]
        assert item["derived"]["period"] == "unknown"
        assert item["derived"]["period_reason"] == "no_date"
        assert item["derived"]["computed_at"] is None
