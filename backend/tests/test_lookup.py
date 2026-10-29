"""``GET /api/lookup`` (docs/API.md §3.1): prefix before full text, ids lookup, contexts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mdt.domain.comments import create_comment
from mdt.domain.errors import BadFilterError, ValidationError
from mdt.domain.lookup import lookup
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import ALICE, create_project, create_service, focal_org_id
from tests.read_helpers import assert_consistent, create_document, open_copy, update


@dataclass
class Catalog:
    db: Db
    ids: dict[str, str]

    def items(self, **params: str) -> list[dict[str, Any]]:
        resolved = {}
        for key, value in params.items():
            for name, entity_id in sorted(self.ids.items(), key=lambda pair: -len(pair[0])):
                value = value.replace(f"@{name}", entity_id)
            resolved[f"f.{key[2:]}" if key.startswith("f_") else key] = value
        with self.db.session() as session:
            return list(lookup(session, resolved)["items"])

    def names(self, **params: str) -> list[str]:
        names = {entity_id: name for name, entity_id in self.ids.items()}
        return [names.get(item["id"], item["id"]) for item in self.items(**params)]


def build(session: Any) -> dict[str, str]:
    ids: dict[str, str] = {}
    projects: list[tuple[str, dict[str, Any]]] = [
        ("P1", {"slug": "lk-alpha-centre", "name_en": "Alpha Centre"}),
        ("P2", {"slug": "lk-alphabet", "name_en": "Alphabet"}),
        ("P3", {"slug": "lk-centre-alpha", "name_en": "Centre Alpha"}),
        (
            "P4",
            {
                "slug": "lk-hromada",
                "name_en": None,
                "name_uk": "Цифрова громада",
                "aliases": [{"text": "Дія.Громада", "lang": "uk"}],
            },
        ),
    ]
    for name, fields in projects:
        ids[name] = create_project(session, **fields).entity_id
    deleted = create_project(session, slug="lk-deleted", name_en="Alpha deleted")
    soft_delete(session, "project", deleted.entity_id, ALICE, expected_version=1)
    ids["P5"] = deleted.entity_id
    ids["S1"] = create_service(session, ids["P1"], name_en="Alpha service").entity_id
    ids["S2"] = create_service(session, ids["P1"], name_en="Beta service").entity_id
    ids["S3"] = create_service(session, ids["P3"], name_en="Gamma service").entity_id
    ids["D1"] = create_document(
        session,
        "Alpha report",
        publisher="Example Publisher",
        published="2024-05",
        published_basis="stated_in_source",
    ).entity_id
    ids["ORG"] = focal_org_id(session)
    update(session, "organization", ids["ORG"], country="ua")
    ids["VIEW"] = apply_change(
        session,
        "saved_view",
        None,
        {"name": "Alpha view", "entity_type": "service", "query": "sort=name_en"},
        ALICE,
    ).entity_id
    ids["C1"] = create_comment(session, ids["P2"], "A comment", ALICE, field="name_en").entity_id
    return ids


@pytest.fixture(scope="module")
def catalog(
    tmp_path_factory: pytest.TempPathFactory, template_db: Path, codebook_dir: Path, seed_dir: Path
) -> Iterator[Catalog]:
    database = open_copy(tmp_path_factory, template_db, codebook_dir, seed_dir, "lookup")
    try:
        with database.session() as session:
            ids = build(session)
        yield Catalog(database, ids)
        assert_consistent(database)
    finally:
        database.engine.dispose()


def test_prefix_matches_rank_before_full_text_matches(catalog: Catalog) -> None:
    # prefix: "Alpha Centre" < "Alphabet" (by label); full text only: "Centre Alpha"
    assert catalog.names(types="project", q="alpha") == ["P1", "P2", "P3"]


def test_exact_match_ranks_first(catalog: Catalog) -> None:
    assert catalog.names(types="project", q="ALPHABET") == ["P2"]
    # exact "Alpha Centre" first; "Centre Alpha" matches both words in full text only
    assert catalog.names(types="project", q="alpha centre") == ["P1", "P3"]


def test_prefix_on_cyrillic_names_aliases_and_slugs(catalog: Catalog) -> None:
    assert catalog.names(types="project", q="ЦИФР") == ["P4"]
    assert catalog.names(types="project", q="дія.гр") == ["P4"]
    assert catalog.names(types="project", q="lk-centre") == ["P3"]


def test_types_are_merged_by_quality_then_label(catalog: Catalog) -> None:
    assert catalog.names(types="project,service", q="alpha") == ["P1", "S1", "P2", "P3"]


def test_default_types_are_the_table_types(catalog: Catalog) -> None:
    names = catalog.names(q="alpha")
    assert names == ["P1", "D1", "S1", "P2", "P3"]  # saved views are not a table type


def test_deleted_rows_are_not_offered(catalog: Catalog) -> None:
    assert "P5" not in catalog.names(types="project", q="alpha deleted")


def test_items_carry_type_label_deleted_flag_and_context(catalog: Catalog) -> None:
    items = {
        item["id"]: item for item in catalog.items(types="project,service,document", q="alpha")
    }
    service = items[catalog.ids["S1"]]
    assert service == {
        "id": catalog.ids["S1"],
        "type": "service",
        "label": "Alpha service",
        "deleted": False,
        "context": "Alpha Centre",
    }
    assert items[catalog.ids["P1"]]["context"] is None
    assert items[catalog.ids["D1"]]["context"] == "Example Publisher · 2024-05"


def test_filters_apply_to_the_types_that_have_the_field(catalog: Catalog) -> None:
    assert catalog.names(types="service", q="", f_project_id="in:@P1") == ["S1", "S2"]
    assert catalog.names(types="service", q="service", f_project_id="in:@P3") == ["S3"]
    # projects have no project_id, so the filter leaves them alone
    assert catalog.names(types="project,service", q="alpha", f_project_id="in:@P3") == [
        "P1",
        "P2",
        "P3",
    ]


def test_filter_on_a_field_no_requested_type_has_is_a_bad_filter(catalog: Catalog) -> None:
    with pytest.raises(BadFilterError):
        catalog.items(types="project", q="alpha", f_project_id="in:x")


def test_empty_query_lists_rows_by_label(catalog: Catalog) -> None:
    assert catalog.names(types="service") == ["S1", "S2", "S3"]
    assert catalog.names(types="service", limit="2") == ["S1", "S2"]


def test_limit(catalog: Catalog) -> None:
    assert catalog.names(types="project,service", q="alpha", limit="2") == ["P1", "S1"]
    for limit in ("0", "101", "x"):
        with pytest.raises(ValidationError):
            catalog.items(q="alpha", limit=limit)


@pytest.mark.parametrize("types", ["unknown", "project,comment"])
def test_unknown_types_are_rejected(catalog: Catalog, types: str) -> None:
    with pytest.raises(ValidationError):
        catalog.items(types=types, q="alpha")


def test_overlong_query_is_rejected(catalog: Catalog) -> None:
    with pytest.raises(ValidationError):
        catalog.items(q="x" * 201)


def test_ids_lookup_includes_deleted_rows_and_keeps_the_order(catalog: Catalog) -> None:
    ids = catalog.ids
    items = catalog.items(ids=f"{ids['P5']},{ids['P1']},prj_01J00000000000000000000000,{ids['P1']}")
    assert [(item["id"], item["deleted"]) for item in items] == [
        (ids["P5"], True),
        (ids["P1"], False),
    ]


def test_ids_lookup_labels_any_type_with_contexts(catalog: Catalog) -> None:
    ids = catalog.ids
    items = {
        item["id"]: item
        for item in catalog.items(ids=",".join([ids["C1"], ids["VIEW"], ids["ORG"], ids["S3"]]))
    }
    assert items[ids["C1"]]["label"] == "Comment on Alphabet · Name (English)"
    assert items[ids["C1"]]["type"] == "comment"
    assert items[ids["VIEW"]]["context"] == "Services"
    assert items[ids["ORG"]]["context"] == "UA"
    assert items[ids["S3"]]["context"] == "Centre Alpha"


def test_ids_lookup_limit(catalog: Catalog) -> None:
    many = ",".join(f"prj_{index:026d}" for index in range(201))
    with pytest.raises(ValidationError):
        catalog.items(ids=many)


def test_vocabulary_term_lookup(db: Db) -> None:
    with db.session() as session:
        items = lookup(session, {"types": "vocabulary_term", "q": "status:act"})["items"]
    assert [(item["label"], item["context"]) for item in items] == [
        ("status:active", "Example active")
    ]
