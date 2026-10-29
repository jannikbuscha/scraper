"""The entity registry against DATA_MODEL §2-§3 and docs/API.md §2-§3.1."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Table

from mdt.config import REPO_ROOT
from mdt.db.models import ENTITY_MODELS
from mdt.domain.registry import (
    CURATED_TYPES,
    ENTITY_TYPES,
    GROUPS,
    PREFIXES,
    TABLE_TYPES,
    TRASH_DEFAULT_SORT,
    PeriodParameters,
    generic_types,
    meta_entity_types,
    type_of_id,
)
from mdt.domain.vocab import load_vocabulary_files

PARAMETERS = PeriodParameters(date(2011, 7, 15), date(2016, 3, 10))
COMMON_COLUMNS = {
    "id",
    "version",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "merged_into",
    "field_meta",
}
META_KEYS = {
    "name",
    "label",
    "type",
    "vocabulary",
    "ref_types",
    "group",
    "required",
    "editable",
    "create_only",
    "system",
    "tracked",
    "derived",
    "virtual",
    "filter",
    "sortable",
    "in_list",
    "in_create",
    "default",
    "bulk_editable",
    "exportable",
    "help",
}


def test_every_multiselect_field_is_sortable() -> None:
    for spec in ENTITY_TYPES.values():
        for field in spec.fields:
            if field.filter == "multiselect":
                assert field.sortable, f"{spec.name}.{field.name}"


def test_bulk_editable_rule() -> None:
    for spec in ENTITY_TYPES.values():
        for field in spec.fields:
            expected = (
                field.editable
                and not field.create_only
                and field.type in ("vocab", "vocab_list", "bool")
            )
            assert field.bulk_editable == expected, f"{spec.name}.{field.name}"
    assert ENTITY_TYPES["project"].field("verification_status").bulk_editable
    assert ENTITY_TYPES["project"].field("in_paper_scope").bulk_editable
    assert not ENTITY_TYPES["evidence"].field("subject_id").bulk_editable


def test_registry_and_models_describe_the_same_columns() -> None:
    for name, spec in ENTITY_TYPES.items():
        table = ENTITY_MODELS[name].__table__
        assert isinstance(table, Table)
        registry_columns = {column for field in spec.stored_fields for column in field.columns}
        model_columns = {column.name for column in table.columns} - COMMON_COLUMNS
        if not spec.curated:
            model_columns -= {"field_meta"}
        if spec.curated:
            registry_columns -= {"verification_status", "notes"}
            model_columns -= {"verification_status", "notes"}
        assert registry_columns == model_columns, name


def test_all_stored_curated_fields_are_tracked_except_seed_key() -> None:
    for name in CURATED_TYPES:
        for field in ENTITY_TYPES[name].stored_fields:
            assert field.tracked == (field.name != "seed_key"), f"{name}.{field.name}"


def test_comment_tracking_and_create_only_fields() -> None:
    comment = ENTITY_TYPES["comment"]
    assert [f.name for f in comment.tracked_fields] == [
        "body_md",
        "status",
        "resolved_by",
        "resolved_at",
    ]
    assert {f.name for f in comment.fields if f.create_only} == {
        "subject_id",
        "field",
        "parent_id",
    }


def test_system_columns_are_registry_fields() -> None:
    for spec in ENTITY_TYPES.values():
        for name in ("created_at", "updated_at", "deleted_at"):
            field = spec.field(name)
            assert (field.type, field.filter, field.sortable, field.group) == (
                "datetime",
                "date_range",
                True,
                "system",
            )
            assert field.system and not field.editable and not field.tracked
        for name in ("created_by", "updated_by", "deleted_by"):
            field = spec.field(name)
            assert (field.type, field.filter, field.sortable) == ("string", "text", True)
        assert spec.field("version").type == "int"
        assert spec.field("version").sortable


def test_common_curated_fields_and_virtual_counts() -> None:
    for name in CURATED_TYPES:
        spec = ENTITY_TYPES[name]
        status = spec.field("verification_status")
        assert (status.vocabulary, status.default, status.filter, status.in_list) == (
            "verification_status",
            "unverified",
            "multiselect",
            True,
        )
        assert spec.field("notes").group == "sources"
        open_comments = spec.field("open_comments")
        assert open_comments.virtual and open_comments.filter == "number_range"
        assert open_comments.sortable
        assert open_comments.in_list == (name in TABLE_TYPES)
        assert spec.field("comment_count").filter == "number_range"


def test_seed_key_is_internal() -> None:
    for name in ("project", "organization"):
        spec = ENTITY_TYPES[name]
        assert spec.field("seed_key").internal
        assert "seed_key" not in {f.name for f in spec.api_fields}
        assert "seed_key" not in {f["name"] for f in spec.meta(PARAMETERS)["fields"]}


@pytest.mark.parametrize(
    ("entity_type", "expected"),
    [
        (
            "project",
            {
                "slug",
                "name_en",
                "name_uk",
                "in_paper_scope",
                "status",
                "paper_cluster",
                "ministry_categories",
                "policy_domains",
                "wartime_relevance",
                "launch",
                "period",
                "verification_status",
                "open_comments",
            },
        ),
        (
            "service",
            {
                "project_id",
                "name_en",
                "name_uk",
                "status",
                "kind",
                "channels",
                "beneficiaries",
                "wartime_relevance",
                "launch",
                "period",
                "verification_status",
                "open_comments",
            },
        ),
        (
            "event",
            {
                "subject_id",
                "event_type",
                "date",
                "date_basis",
                "description_en",
                "verification_status",
                "open_comments",
            },
        ),
        (
            "document",
            {
                "title",
                "publisher",
                "doc_type",
                "language",
                "published",
                "screening_status",
                "verification_status",
                "open_comments",
            },
        ),
        (
            "organization",
            {
                "slug",
                "name_en",
                "name_uk",
                "org_type",
                "country",
                "verification_status",
                "open_comments",
            },
        ),
    ],
)
def test_default_list_columns(entity_type: str, expected: set[str]) -> None:
    assert {f.name for f in ENTITY_TYPES[entity_type].fields if f.in_list} == expected


@pytest.mark.parametrize(
    ("entity_type", "required"),
    [
        ("project", {"slug", "in_paper_scope", "verification_status"}),
        ("service", {"project_id", "verification_status"}),
        ("event", {"subject_id", "event_type", "verification_status"}),
        ("document", {"title", "screening_status", "verification_status"}),
        ("organization", {"verification_status"}),
        ("participation", {"organization_id", "subject_id", "role", "verification_status"}),
        ("relation", {"from_id", "to_id", "relation_type", "verification_status"}),
        ("indicator", {"subject_id", "metric", "value", "verification_status"}),
        ("evidence", {"subject_id", "target", "verification_status"}),
        ("vocabulary_term", {"vocabulary", "code", "label_en", "verification_status"}),
        ("saved_view", {"name", "entity_type", "query", "verification_status"}),
    ],
)
def test_required_fields(entity_type: str, required: set[str]) -> None:
    assert {f.name for f in ENTITY_TYPES[entity_type].fields if f.required} == required


def test_create_only_and_system_fields() -> None:
    create_only = {
        (spec.name, f.name) for spec in ENTITY_TYPES.values() for f in spec.fields if f.create_only
    }
    assert create_only == {
        ("evidence", "subject_id"),
        ("evidence", "target"),
        ("vocabulary_term", "vocabulary"),
        ("vocabulary_term", "code"),
        ("comment", "subject_id"),
        ("comment", "field"),
        ("comment", "parent_id"),
    }
    document = ENTITY_TYPES["document"]
    for name in (
        "canonical_url",
        "published_at_utc",
        "source_id",
        "external_id",
        "raw_snapshot_id",
        "text_hash",
        "extraction_method",
    ):
        assert document.field(name).system and not document.field(name).editable
    assert ENTITY_TYPES["service"].field("source_categories").system
    assert ENTITY_TYPES["evidence"].field("value_snapshot").system


def test_derived_and_virtual_fields() -> None:
    for name in ("project", "service"):
        spec = ENTITY_TYPES[name]
        assert spec.has_derived
        derived = {f.name: f for f in spec.fields if f.derived}
        assert set(derived) == {
            "launch",
            "existed_by",
            "period",
            "war_trajectory",
            "portfolio_entry",
        }
        assert derived["launch"].type == "partial_date"
        assert derived["existed_by"].type == "date"
        assert derived["period"].vocabulary == "period"
        assert all(f.sortable and f.group == "wartime" and not f.editable for f in derived.values())
    assert ENTITY_TYPES["service"].field("project_in_paper_scope").filter == "bool"
    assert ENTITY_TYPES["event"].field("subject_in_paper_scope").filter == "bool"
    document = ENTITY_TYPES["document"]
    assert document.field("linked_in_paper_scope").filter == "bool"
    assert document.field("text").detail_only and document.field("text").filter is None
    assert document.field("links").filter == "ref"
    endpoint = ENTITY_TYPES["relation"].field("endpoint")
    assert endpoint.virtual and endpoint.filter == "ref" and not endpoint.sortable


def test_defaults_in_meta() -> None:
    assert ENTITY_TYPES["project"].field("in_paper_scope").default is False
    assert ENTITY_TYPES["document"].field("screening_status").default == "unscreened"
    assert ENTITY_TYPES["vocabulary_term"].field("active").default is True


def test_constraints() -> None:
    names = [{"one_of_required": ["name_en", "name_uk"]}]
    for name in ("project", "service", "organization", "component"):
        assert ENTITY_TYPES[name].meta(PARAMETERS)["constraints"] == names
    assert ENTITY_TYPES["evidence"].meta(PARAMETERS)["constraints"] == [
        {"one_of_required": ["document_id", "url"]}
    ]


def test_create_form_fields() -> None:
    project = {f.name for f in ENTITY_TYPES["project"].fields if f.in_create}
    assert {"slug", "name_en", "name_uk", "in_paper_scope", "scope_note"} <= project
    assert not {"verification_status", "launch", "seed_key", "created_at"} & project
    evidence = {f.name for f in ENTITY_TYPES["evidence"].fields if f.in_create}
    assert {"subject_id", "target", "url", "retrieved_at", "quote"} <= evidence


def test_meta_shape() -> None:
    meta = meta_entity_types(PARAMETERS)
    assert set(meta) == {spec.name for spec in generic_types()}
    assert "comment" not in meta
    project = meta["project"]
    assert project["label"] == "Project" and project["label_plural"] == "Projects"
    assert project["prefix"] == "prj" and project["table_view"] is True
    assert meta["participation"]["table_view"] is False
    for entity in meta.values():
        for field in entity["fields"]:
            assert set(field) == META_KEYS
    assert [group["key"] for group in GROUPS] == [
        "basics",
        "classification",
        "wartime",
        "framework",
        "sources",
        "system",
    ]


def test_default_sorts() -> None:
    assert {name: spec.default_sort for name, spec in ENTITY_TYPES.items() if spec.generic_api} == {
        "project": "paper_cluster,name_en",
        "service": "project_id,name_en",
        "event": "-date",
        "document": "-published",
        "organization": "name_en",
        "participation": "organization_id",
        "component": "name_en",
        "relation": "relation_type",
        "indicator": "-as_of",
        "evidence": "-created_at",
        "vocabulary_term": "vocabulary,sort_order",
        "saved_view": "name",
    }
    assert TRASH_DEFAULT_SORT == "-deleted_at"
    for spec in ENTITY_TYPES.values():
        for part in spec.default_sort.split(","):
            assert spec.field(part.lstrip("-")).sortable


def test_quick_filters() -> None:
    meta = meta_entity_types(PARAMETERS)

    def queries(entity_type: str) -> dict[str, str | None]:
        return {f["key"]: f.get("query") for f in meta[entity_type]["quick_filters"]}

    assert queries("project") == {
        "unverified": "f.verification_status=in:unverified",
        "open_comments": "f.open_comments=range:1..",
        "no_start_date": "f.launch=empty:true",
        "in_scope": "f.in_paper_scope=eq:true",
        "period": None,
    }
    chips = meta["project"]["quick_filters"][-1]
    assert (chips["kind"], chips["field"]) == ("chips", "period")
    assert queries("service")["in_scope"] == "f.project_in_paper_scope=eq:true"
    assert queries("event") == {
        "unverified": "f.verification_status=in:unverified",
        "open_comments": "f.open_comments=range:1..",
        "undated": "f.date=empty:true",
        "in_scope": "f.subject_in_paper_scope=eq:true",
        "period": None,
    }

    def presets(entity_type: str) -> dict[str, Any]:
        groups: list[dict[str, Any]] = [
            f for f in meta[entity_type]["quick_filters"] if f["kind"] == "preset"
        ]
        assert len(groups) == 1
        return groups[0]

    # The period presets form one quick filter with a list of {key, label, query}.
    event_presets = presets("event")
    assert (event_presets["key"], event_presets["label"]) == ("period", "Period")
    assert event_presets["field"] == "date"
    assert "query" not in event_presets
    assert {p["key"]: p["query"] for p in event_presets["presets"]} == {
        "pre_ministry": "f.date=within:..2011-07-14",
        "pre_invasion": "f.date=within:2011-07-15..2016-03-09",
        "full_scale_war": "f.date=within:2016-03-10..",
    }
    assert all(set(p) == {"key", "label", "query"} for p in event_presets["presets"])
    document = queries("document")
    assert document["unscreened"] == "f.screening_status=in:unscreened"
    assert document["in_scope"] == "f.linked_in_paper_scope=eq:true"
    document_presets = presets("document")
    assert document_presets["field"] == "published"
    assert document_presets["presets"][-1]["query"] == "f.published=within:2016-03-10.."
    assert queries("organization") == {
        "unverified": "f.verification_status=in:unverified",
        "open_comments": "f.open_comments=range:1..",
    }
    assert queries("participation") == {}
    # Without parameters there are no presets.
    assert "period" not in {f["key"] for f in ENTITY_TYPES["event"].meta()["quick_filters"]}


def test_quick_filter_fields_exist_and_are_filterable() -> None:
    meta = meta_entity_types(PARAMETERS)
    for entity_type, entity in meta.items():
        spec = ENTITY_TYPES[entity_type]
        for quick in entity["quick_filters"]:
            field = quick.get("field") or quick["query"].split("=")[0].removeprefix("f.")
            assert spec.field(field).filter is not None


def test_references_and_vocabularies_are_declared() -> None:
    codebook = {vocabulary.name for vocabulary in load_vocabulary_files(REPO_ROOT / "codebook")}
    for spec in ENTITY_TYPES.values():
        for field in spec.fields:
            if field.type in ("vocab", "vocab_list"):
                assert field.vocabulary in codebook, f"{spec.name}.{field.name}"
            if field.type in ("ref", "doc_links"):
                assert field.ref_types, f"{spec.name}.{field.name}"
                assert set(field.ref_types) <= set(ENTITY_TYPES)


def test_prefixes() -> None:
    assert len(PREFIXES) == len(ENTITY_TYPES)
    assert PREFIXES["prj"] == "project"
    assert PREFIXES["cmt"] == "comment"
    assert type_of_id("svc_01JBX3ABCDEFGHJKMNPQRSTVWX") == "service"
    assert type_of_id("svc_01jbx3abcdefghjkmnpqrstvwx") is None
    assert type_of_id("abc_01JBX3ABCDEFGHJKMNPQRSTVWX") is None
    assert type_of_id("project") is None
