"""Meta, vocabulary, statistics, lookup and health endpoints (API §3.1). Expected values
are derived from the real codebook and seed files, never written into the tests."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi.testclient import TestClient

from mdt import __version__
from mdt.db.migrate import head_revision
from mdt.domain.registry import GROUPS, TABLE_TYPES, generic_types
from mdt.domain.seed import load_seed_file
from mdt.domain.vocab import load_parameters, load_vocabulary_files
from tests.api.conftest import REAL_CODEBOOK, REAL_SEED
from tests.api.helpers import ApiClient, error_of


def seed_projects() -> list[dict[str, Any]]:
    """The project entries of ``seed/projects.yaml``."""
    return load_seed_file(REAL_SEED / "projects.yaml").sections["project"]


def test_health(raw_client: TestClient) -> None:
    response = raw_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "schema_revision": head_revision(),
    }


def test_meta_document(client: ApiClient) -> None:
    meta = client.ok(client.get("/api/meta"))
    assert set(meta) == {
        "app_version",
        "team_members",
        "focal_org_id",
        "parameters",
        "limits",
        "groups",
        "vocabularies",
        "entity_types",
    }
    assert meta["app_version"] == __version__
    assert meta["team_members"] == ["Alice Example", "Bob Example"]
    assert meta["parameters"] == load_parameters(REAL_CODEBOOK).as_api()
    assert meta["limits"] == {
        "max_comment_chars": 10_000,
        "max_note_chars": 2_000,
        "max_page_size": 500,
        "max_bulk_items": 500,
        "max_export_rows": 200_000,
    }
    assert meta["groups"] == [dict(group) for group in GROUPS]
    files = {vocabulary.name: vocabulary for vocabulary in load_vocabulary_files(REAL_CODEBOOK)}
    assert set(meta["vocabularies"]) == set(files)
    for name, entry in meta["vocabularies"].items():
        assert entry == {
            "label": files[name].label,
            "multi": files[name].multi,
            "fixed_codes": files[name].fixed_codes,
        }
    assert set(meta["entity_types"]) == {spec.name for spec in generic_types()}
    assert "comment" not in meta["entity_types"]


def test_meta_focal_org_is_the_seeded_organisation(client: ApiClient) -> None:
    meta = client.ok(client.get("/api/meta"))
    organizations = client.list("organization")["items"]
    assert [item["id"] for item in organizations] == [meta["focal_org_id"]]


def test_meta_entity_types(client: ApiClient) -> None:
    types = client.ok(client.get("/api/meta"))["entity_types"]
    project = types["project"]
    assert project["label"] == "Project" and project["prefix"] == "prj"
    assert project["table_view"] is True
    assert project["default_sort"] == "paper_cluster,name_en"
    assert project["constraints"] == [{"one_of_required": ["name_en", "name_uk"]}]
    assert [quick["key"] for quick in project["quick_filters"]] == [
        "unverified",
        "open_comments",
        "no_start_date",
        "in_scope",
        "period",
    ]
    fields = {field["name"]: field for field in project["fields"]}
    assert "seed_key" not in fields
    assert fields["paper_cluster"]["bulk_editable"] is True
    assert fields["period"]["derived"] is True and fields["open_comments"]["virtual"] is True
    # The tooltip of the derived launch names the interval that sorting and filters use.
    assert "interval over all candidates" in fields["launch"]["help"]
    # The tooltips of period and war trajectory name every input of their rules (CODEBOOK
    # §2.7): without a launch, an archive bound before the founding day gives pre_ministry,
    # and an archive bound before the invasion shows that the item existed before it.
    for name in ("period", "war_trajectory"):
        assert "launch interval" in fields[name]["help"], name
        assert "archive bound" in fields[name]["help"], name
    assert "modification events" in fields["war_trajectory"]["help"]
    documents = {field["name"]: field for field in types["document"]["fields"]}
    assert documents["text"]["exportable"] is False
    assert fields["open_comments"]["exportable"] is True
    assert set(fields["slug"]) >= {"name", "type", "group", "filter", "sortable", "help"}
    assert {name for name, spec in types.items() if spec["table_view"]} == set(TABLE_TYPES)
    parameters = load_parameters(REAL_CODEBOOK)
    (period,) = [quick for quick in types["event"]["quick_filters"] if quick["kind"] == "preset"]
    assert (period["key"], period["field"]) == ("period", "date")
    assert period["presets"][-1]["query"] == f"f.date=within:{parameters.full_scale_invasion}.."


def test_vocab_listing(client: ApiClient) -> None:
    listing = client.ok(client.get("/api/vocab"))["vocabularies"]
    files = {vocabulary.name: vocabulary for vocabulary in load_vocabulary_files(REAL_CODEBOOK)}
    assert [vocabulary["name"] for vocabulary in listing] == sorted(files)
    by_name = {vocabulary["name"]: vocabulary for vocabulary in listing}
    for name, vocabulary_file in files.items():
        assert {term["code"] for term in by_name[name]["terms"]} == {
            term["code"] for term in vocabulary_file.terms
        }
    term = by_name["paper_cluster"]["terms"][0]
    assert set(term) == {
        "id", "code", "label_en", "label_uk", "definition", "include_note", "exclude_note",
        "examples", "sort_order", "active", "replaced_by", "attributes", "version",
        "usage_count", "open_comments",
    }  # fmt: skip
    clusters = Counter(p["paper_cluster"] for p in seed_projects() if p.get("paper_cluster"))
    usage = {term["code"]: term["usage_count"] for term in by_name["paper_cluster"]["terms"]}
    assert usage == {code: clusters.get(code, 0) for code in usage}


def test_stats(client: ApiClient) -> None:
    stats = client.ok(client.get("/api/stats"))
    assert stats["entities"]["project"] == {
        "total": len(seed_projects()),
        "unverified": len(seed_projects()),
        "deleted": 0,
    }
    assert stats["entities"]["organization"]["total"] == 1
    assert set(stats["entities"]) == {spec.name for spec in generic_types()}
    assert stats["open_comments"] == 0
    project = client.list("project")["items"][0]
    client.comment(project["id"])
    assert client.ok(client.get("/api/stats"))["open_comments"] == 1


def test_lookup_by_prefix_and_by_ids(client: ApiClient) -> None:
    first = seed_projects()[0]
    name = first["name_en"]
    found = client.ok(client.get("/api/lookup", {"types": "project", "q": name[:3]}))["items"]
    assert any(item["label"] == name for item in found)
    assert all(set(item) == {"id", "type", "label", "deleted", "context"} for item in found)
    target = next(item for item in found if item["label"] == name)
    unknown = "prj_01JBX3AAAAAAAAAAAAAAAAAAAA"
    by_ids = client.ok(client.get("/api/lookup", {"ids": f"{target['id']},{unknown}"}))
    assert by_ids["items"] == [target | {"context": by_ids["items"][0]["context"]}]


def test_lookup_validation(client: ApiClient) -> None:
    response = client.get("/api/lookup", {"limit": "0"})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
    response = client.get("/api/lookup", {"q": "x" * 201})
    assert (response.status_code, error_of(response)["code"]) == (400, "validation_error")
