"""Import plans and runs (importers/tabular.py; docs/COLLECTORS.md §9.4, docs/DATA_MODEL.md
§17.1). All values are synthetic; codes come from the synthetic test codebook."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from mdt.collectors.store import SnapshotStore
from mdt.db.models import ImportRun, Project, Revision
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import NotFoundError, ValidationError
from mdt.domain.records import field_meta_of, load_row
from mdt.domain.registry import ENTITY_TYPES
from mdt.domain.revisions import apply_change, restore_version, set_field_verification, soft_delete
from mdt.importers import tabular
from mdt.importers.tabular import (
    ImportRequest,
    Plan,
    conflict_reason,
    dry_run_import,
    file_label,
    get_import,
    list_imports,
    preview_import,
    run_import,
)
from tests.conftest import Db
from tests.helpers import create_project
from tests.importers.test_files_and_mapping import xlsx_bytes


def _upload(db: Db, body: bytes, filename: str = "projects.csv") -> str:
    with db.session() as session:
        return SnapshotStore(db.settings.raw_path).put_upload(session, [body], filename).id


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def _project(db: Db, project_id: str) -> dict[str, Any]:
    spec = ENTITY_TYPES["project"]
    with db.session() as session, read_transaction(session):
        row = load_row(session, spec, project_id)
        assert row is not None
        return {**row, "field_meta": field_meta_of(spec, row)}


def _revisions(db: Db) -> int:
    with db.session() as session, read_transaction(session):
        return int(session.scalar(select(func.count()).select_from(Revision)) or 0)


def _imports(db: Db) -> int:
    with db.session() as session, read_transaction(session):
        return int(session.scalar(select(func.count()).select_from(ImportRun)) or 0)


def _run(db: Db, upload_id: str, **request: Any) -> tabular.ImportResult:
    with db.session() as session:
        return run_import(session, db.settings, ImportRequest(upload_id=upload_id, **request))


def _dry(db: Db, upload_id: str, **request: Any) -> Plan:
    with db.session() as session:
        return dry_run_import(session, db.settings, ImportRequest(upload_id=upload_id, **request))


MAPPING = {"slug": "slug", "name": "name_en", "scope": "scope_note", "status": "status"}


def test_preview(db: Db) -> None:
    rows = [f"example-{index},Example {index},Synthetic scope,active" for index in range(25)]
    upload_id = _upload(db, _csv("slug,Name (English),scope,status", *rows))
    with db.session() as session:
        preview = preview_import(session, db.settings, upload_id, "project", None)
    assert preview["sheets"] is None
    assert preview["columns"] == ["slug", "Name (English)", "scope", "status"]
    assert len(preview["preview"]) == 20
    assert preview["preview"][0] == ["example-0", "Example 0", "Synthetic scope", "active"]
    assert preview["suggested_mapping"] == {
        "slug": "slug",
        "Name (English)": "name_en",
        "status": "status",
    }
    assert "scope_note" in preview["importable_fields"]
    assert preview["key_fields"] == ["id", "slug"]


def test_preview_pads_short_rows_and_lists_sheets(db: Db) -> None:
    upload_id = _upload(
        db, xlsx_bytes({"One": [["slug", "notes"], ["example-a"]], "Two": [["x"]]}), "data.xlsx"
    )
    with db.session() as session:
        preview = preview_import(session, db.settings, upload_id, "project", None)
    assert preview["sheets"] == ["One", "Two"]
    assert preview["preview"] == [["example-a", ""]]


def test_preview_needs_an_upload_and_a_table_type(db: Db) -> None:
    upload_id = _upload(db, _csv("slug"))
    with db.session() as session:
        with pytest.raises(ValidationError) as error:
            preview_import(session, db.settings, "raw_unknown", "project", None)
        assert set(error.value.details or {}) == {"upload_id"}
        with pytest.raises(ValidationError) as error:
            preview_import(session, db.settings, upload_id, "comment", None)
        assert set(error.value.details or {}) == {"entity_type"}


def test_a_dry_run_plans_and_writes_nothing(db: Db) -> None:
    with db.session() as session:
        create_project(session, slug="example-old", name_en="Old name")
    upload_id = _upload(
        db,
        _csv(
            "slug,name,scope,status",
            "example-new,Example new,Synthetic scope,active",
            "example-old,New name,,",
            "example-bad,Example bad,Synthetic scope,no-such-status",
        ),
    )
    before = (_revisions(db), _imports(db))
    plan = _dry(db, upload_id, entity_type="project", mapping=MAPPING, key_field="slug")
    assert (_revisions(db), _imports(db)) == before
    assert plan.stats == {
        "rows": 3,
        "create": 1,
        "update": 0,
        "unchanged": 1,
        "conflicts": 1,
        "errors": 1,
    }
    api = plan.as_api()
    assert [row["row"] for row in api["rows"]] == [4, 3, 2]  # errors, conflicts, the rest
    error, conflict, create = api["rows"]
    assert error["action"] == "error" and set(error["errors"]) == {"status"}
    assert conflict["action"] == "unchanged" and conflict["id"] is not None
    assert conflict["conflicts"] == [
        {"field": "name_en", "current": "Old name", "new": "New name", "reason": "manual"}
    ]
    assert create["action"] == "create" and create["id"] is None
    assert create["changes"]["slug"] == [None, "example-new"]


def test_a_run_writes_with_import_provenance_and_a_batch(db: Db) -> None:
    upload_id = _upload(
        db,
        _csv(
            "slug,name,scope,status",
            "example-new,Example new,Synthetic scope,active",
            "example-other,Example other,Synthetic scope,",
        ),
        "my projects.csv",
    )
    result = _run(
        db,
        upload_id,
        entity_type="project",
        mapping=MAPPING,
        key_field="slug",
        note="Synthetic import",
    )
    run = result.import_run
    assert run["status"] == "done" and run["error"] is None
    assert run["stats"]["create"] == 2 and run["errors"] == []
    assert run["mapping"] == MAPPING and run["key_field"] == "slug"
    with db.session() as session:
        record = SnapshotStore(db.settings.raw_path).record(session, upload_id)
    assert record is not None and run["file_label"] == file_label(record)
    assert run["file_label"].startswith("my projects.csv#")
    created = [row.id for row in result.plan.rows]
    assert all(created)
    project = _project(db, created[0] or "")
    meta = project["field_meta"]["name_en"]
    assert meta["src"] == f"import:{run['file_label']}" and meta["locked"] is True
    assert project["created_by"] == f"import:{run['file_label']}"
    with db.session() as session, read_transaction(session):
        revisions = session.execute(
            select(Revision.channel, Revision.batch_id, Revision.note).where(
                Revision.entity_id.in_(created)
            )
        ).all()
    assert {tuple(row) for row in revisions} == {("import", run["id"], "Synthetic import")}


def test_running_the_same_import_again_writes_no_revision(db: Db) -> None:
    upload_id = _upload(db, _csv("slug,name,scope", "example-a,Example A,Synthetic scope"))
    _run(db, upload_id, entity_type="project", mapping=MAPPING_NO_STATUS, key_field="slug")
    before = _revisions(db)
    again = _run(db, upload_id, entity_type="project", mapping=MAPPING_NO_STATUS, key_field="slug")
    assert _revisions(db) == before
    assert again.plan.stats["unchanged"] == 1 and again.import_run["status"] == "done"


MAPPING_NO_STATUS = {"slug": "slug", "name": "name_en", "scope": "scope_note"}


def test_conflict_reasons_and_overwritable_values(db: Db) -> None:
    with db.session() as session:
        manual = create_project(session, slug="example-manual", name_en="Manual")
        seeded = create_project(session, actor=Actor.seed(), slug="example-seed", name_en="Seeded")
        collected = create_project(
            session,
            actor=Actor.collector("example", "run_example"),
            slug="example-collector",
            name_en="Collected",
        )
        restored = create_project(session, slug="example-restored", name_en="First")
        apply_change(session, "project", restored.entity_id, {"name_en": "Second"}, Actor.ui())
        restore_version(session, "project", restored.entity_id, 1, Actor.restore())
        verified = create_project(session, slug="example-verified", name_en="Verified")
        evidence = apply_change(
            session,
            "evidence",
            None,
            {
                "subject_id": verified.entity_id,
                "target": "field:name_en",
                "url": "https://example.org/source",
                "quote": "Verified",
            },
            Actor.ui(),
        )
        set_field_verification(
            session,
            "project",
            verified.entity_id,
            "name_en",
            "verified",
            Actor.ui(),
            evidence_id=evidence.entity_id,
        )
    upload_id = _upload(
        db,
        _csv(
            "slug,name",
            "example-manual,Imported",
            "example-seed,Imported",
            "example-collector,Imported",
            "example-restored,Imported",
            "example-verified,Imported",
        ),
    )
    result = _run(
        db,
        upload_id,
        entity_type="project",
        mapping={"slug": "slug", "name": "name_en"},
        key_field="slug",
    )
    by_row = {row.row: row for row in result.plan.rows}
    assert [c["reason"] for c in by_row[2].conflicts] == ["manual"]
    assert [c["reason"] for c in by_row[3].conflicts] == ["seed"]
    assert by_row[4].action == "update" and by_row[4].conflicts == []
    assert [c["reason"] for c in by_row[5].conflicts] == ["restored"]
    assert [c["reason"] for c in by_row[6].conflicts] == ["verified"]
    assert _project(db, collected.entity_id)["name_en"] == "Imported"
    for kept, value in ((manual, "Manual"), (seeded, "Seeded"), (verified, "Verified")):
        assert _project(db, kept.entity_id)["name_en"] == value
    assert result.import_run["stats"]["conflicts"] == 4
    assert {item["row"] for item in result.import_run["errors"]} == {2, 3, 5, 6}


def test_a_later_import_overwrites_an_untouched_import_value(db: Db) -> None:
    mapping = {"slug": "slug", "name": "name_en", "notes": "notes", "scope": "scope_note"}
    first = _upload(
        db, _csv("slug,name,notes,scope", "example-a,Example,First note,Synthetic scope"), "a.csv"
    )
    _run(db, first, entity_type="project", mapping=mapping, key_field="slug")
    second = _upload(db, _csv("slug,notes", "example-a,Second note"), "b.csv")
    result = _run(
        db,
        second,
        entity_type="project",
        mapping={"slug": "slug", "notes": "notes"},
        key_field="slug",
    )
    row = result.plan.rows[0]
    assert row.action == "update" and row.changes == {"notes": ["First note", "Second note"]}
    project_id = row.id or ""
    assert (
        _project(db, project_id)["field_meta"]["notes"]["src"]
        == f"import:{result.import_run['file_label']}"
    )
    # Once a person edits the field, the next import reports a conflict instead.
    with db.session() as session:
        apply_change(session, "project", project_id, {"notes": "Person's note"}, Actor.ui())
    third = _upload(db, _csv("slug,notes", "example-a,Third note"), "c.csv")
    again = _run(
        db,
        third,
        entity_type="project",
        mapping={"slug": "slug", "notes": "notes"},
        key_field="slug",
    )
    assert [c["reason"] for c in again.plan.rows[0].conflicts] == ["manual"]


def test_empty_cells_never_clear_and_rows_without_differences_write_nothing(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session, actor=Actor.collector("example", "run_example"), slug="example-a", notes="Kept"
        )
    upload_id = _upload(db, _csv("slug,notes", "example-a,"))
    before = _revisions(db)
    result = _run(
        db,
        upload_id,
        entity_type="project",
        mapping={"slug": "slug", "notes": "notes"},
        key_field="slug",
    )
    assert result.plan.rows[0].action == "unchanged"
    assert _revisions(db) == before
    assert _project(db, project.entity_id)["notes"] == "Kept"


def test_keys_by_id_and_url_and_deleted_matches(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session, actor=Actor.collector("example", "run_example"), slug="example-a"
        )
        gone = create_project(session, slug="example-gone")
        soft_delete(session, "project", gone.entity_id, Actor.ui())
        document = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example",
                "url": "https://example.org/doc",
                "retrieved_at": "2026-10-30T10:00:00Z",
            },
            Actor.collector("example", "run_example"),
        )
    by_id = _upload(
        db,
        _csv(
            "id,notes",
            f"{project.entity_id},Note by ID",
            f"{gone.entity_id},Note",
            "prj_01JBX3AAAAAAAAAAAAAAAAAAAA,Note",
            ",Synthetic",
        ),
    )
    result = _run(
        db, by_id, entity_type="project", mapping={"id": "id", "notes": "notes"}, key_field="id"
    )
    rows = {row.row: row for row in result.plan.rows}
    assert rows[2].action == "update" and rows[2].id == project.entity_id
    assert rows[3].errors == {"id": ["matches a deleted record (entity_deleted)"]}
    assert rows[4].errors == {"id": ["no record of this type has this ID"]}
    # A row without a key creates a record (here it fails validation: no name, no scope).
    assert rows[5].action == "error"
    by_slug = _upload(db, _csv("slug,notes", "example-gone,Note"))
    gone_row = _run(
        db,
        by_slug,
        entity_type="project",
        mapping={"slug": "slug", "notes": "notes"},
        key_field="slug",
    ).plan.rows[0]
    assert gone_row.errors == {"slug": ["matches a deleted record (entity_deleted)"]}
    by_url = _upload(db, _csv("url,notes", "https://EXAMPLE.org/doc/,Document note"), "docs.csv")
    doc_row = _run(
        db,
        by_url,
        entity_type="document",
        mapping={"url": "url", "notes": "notes"},
        key_field="url",
    ).plan.rows[0]
    assert doc_row.action == "update" and doc_row.id == document.entity_id


def test_without_a_key_every_row_creates(db: Db) -> None:
    with db.session() as session:
        create_project(session, slug="example-a")
    upload_id = _upload(db, _csv("slug,name,scope", "example-a,Example,Synthetic scope"))
    row = _run(db, upload_id, entity_type="project", mapping=MAPPING_NO_STATUS).plan.rows[0]
    assert row.action == "error" and row.errors == {"slug": ["is already used by another record"]}


def test_row_errors_do_not_stop_the_other_rows(db: Db) -> None:
    upload_id = _upload(
        db,
        _csv(
            "slug,name,scope,scope_flag,extra",
            "example-a,Example A,Synthetic scope,maybe,",
            "example-b,Example B,,,",
            "example-c,Example C,Synthetic scope,yes,",
            "example-d,Example D,Synthetic scope,,surplus,cell",
        ),
    )
    mapping = {
        "slug": "slug",
        "name": "name_en",
        "scope": "scope_note",
        "scope_flag": "in_paper_scope",
    }
    result = _run(db, upload_id, entity_type="project", mapping=mapping, key_field="slug")
    rows = {row.row: row for row in result.plan.rows}
    assert set(rows[2].errors) == {"in_paper_scope"}
    assert set(rows[3].errors) == {"scope_note"}
    assert rows[4].action == "create"
    assert rows[5].errors == {"row": ["has more cells than the header has columns"]}
    assert result.import_run["stats"]["errors"] == 3


def test_vocabulary_labels_lists_and_references_are_imported(db: Db) -> None:
    with db.session() as session:
        project = create_project(session, slug="example-parent")
    upload_id = _upload(
        db,
        _csv(
            "project,name,channels", "example-parent,Example service,channel_a; Example channel_b"
        ),
        "services.csv",
    )
    mapping = {"project": "project_id", "name": "name_en", "channels": "channels"}
    row = _run(db, upload_id, entity_type="service", mapping=mapping).plan.rows[0]
    assert row.action == "create"
    assert row.changes["project_id"] == [None, project.entity_id]
    assert row.changes["channels"] == [None, ["channel_a", "channel_b"]]


def test_a_scope_change_takes_the_imported_note_along(db: Db) -> None:
    with db.session() as session:
        project = create_project(
            session,
            actor=Actor.collector("example", "run_example"),
            slug="example-a",
            scope_note="Same note",
        )
    upload_id = _upload(db, _csv("slug,scope_flag,scope", "example-a,true,Same note"))
    mapping = {"slug": "slug", "scope_flag": "in_paper_scope", "scope": "scope_note"}
    row = _run(db, upload_id, entity_type="project", mapping=mapping, key_field="slug").plan.rows[0]
    assert row.action == "update", row.errors
    assert _project(db, project.entity_id)["in_paper_scope"] == 1


def _person_kept_note(db: Db, project_id: str, kind: str) -> None:
    """A person's scope note on ``project_id``: set by hand, field-verified, or restored."""
    with db.session() as session:
        if kind == "restored":
            before = int(_project(db, project_id)["version"])
            apply_change(session, "project", project_id, {"scope_note": "Interim"}, Actor.ui())
            restore_version(
                session, "project", project_id, before, Actor.restore(), fields=["scope_note"]
            )
            return
        apply_change(
            session, "project", project_id, {"scope_note": "Example note set by hand"}, Actor.ui()
        )
        if kind == "verified":
            evidence = apply_change(
                session,
                "evidence",
                None,
                {
                    "subject_id": project_id,
                    "target": "field:scope_note",
                    "url": "https://example.org/source",
                    "quote": "Example note set by hand",
                },
                Actor.ui(),
            )
            set_field_verification(
                session,
                "project",
                project_id,
                "scope_note",
                "verified",
                Actor.ui(),
                evidence_id=evidence.entity_id,
            )


@pytest.mark.parametrize("kind", ["manual", "verified", "restored"])
def test_a_scope_change_never_takes_a_conflicting_note_along(db: Db, kind: str) -> None:
    # The project and its scope come from an import; only the scope note is the person's.
    mapping = {"slug": "slug", "name": "name_en", "scope_flag": "in_paper_scope"}
    mapping["scope"] = "scope_note"
    first = _upload(
        db, _csv("slug,name,scope_flag,scope", "example-r,Example,false,Import note A"), "a.csv"
    )
    project_id = _run(db, first, entity_type="project", mapping=mapping, key_field="slug")
    project_id = project_id.plan.rows[0].id or ""
    _person_kept_note(db, project_id, kind)
    kept = _project(db, project_id)
    second = _upload(db, _csv("slug,scope_flag,scope", "example-r,true,Import note B"), "b.csv")
    request: dict[str, Any] = {
        "entity_type": "project",
        "mapping": {"slug": "slug", "scope_flag": "in_paper_scope", "scope": "scope_note"},
        "key_field": "slug",
    }
    planned = _dry(db, second, **request).rows[0]
    result = _run(db, second, **request)
    for row in (planned, result.plan.rows[0]):
        assert row.action == "update", row.errors
        assert row.changes == {"in_paper_scope": [False, True]}
        assert row.conflicts == [
            {
                "field": "scope_note",
                "current": kept["scope_note"],
                "new": "Import note B",
                "reason": kind,
            }
        ]
    after = _project(db, project_id)
    assert after["in_paper_scope"] == 1
    assert after["scope_note"] == kept["scope_note"]  # what the dry run and result report
    assert after["field_meta"]["scope_note"] == kept["field_meta"]["scope_note"]


def test_a_fatal_error_is_recorded_and_earlier_rows_stay(
    db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = _upload(
        db,
        _csv(
            "slug,name,scope",
            "example-a,Example A,Synthetic scope",
            "example-b,Example B,Synthetic scope",
        ),
    )
    original = tabular.plan_row
    calls: list[int] = []

    def failing(*args: Any, **kwargs: Any) -> tabular.RowResult:
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("database gone")
        return original(*args, **kwargs)

    monkeypatch.setattr(tabular, "plan_row", failing)
    result = _run(db, upload_id, entity_type="project", mapping=MAPPING_NO_STATUS, key_field="slug")
    assert result.import_run["status"] == "failed"
    assert result.import_run["error"] == "unexpected error: RuntimeError"
    assert result.import_run["stats"]["create"] == 1
    with db.session() as session, read_transaction(session):
        assert session.scalar(select(Project.id).where(Project.slug == "example-a")) is not None


def test_plans_keep_at_most_500_rows_errors_first(db: Db) -> None:
    lines = [f"example-{index},maybe" for index in range(510)]
    upload_id = _upload(db, _csv("slug,flag", *lines))
    plan = _dry(
        db, upload_id, entity_type="project", mapping={"slug": "slug", "flag": "in_paper_scope"}
    )
    api = plan.as_api()
    assert api["stats"]["errors"] == 510 and len(api["rows"]) == 500


def test_invalid_requests_are_refused_before_anything_is_written(db: Db) -> None:
    upload_id = _upload(db, _csv("slug,name", "example-a,Example"))
    before = (_revisions(db), _imports(db))
    with pytest.raises(ValidationError) as error:
        _run(db, upload_id, entity_type="project", mapping={"name": "seed_key"})
    assert set(error.value.details or {}) == {"mapping.name"}
    with pytest.raises(ValidationError):
        _run(db, upload_id, entity_type="project", mapping={"name": "name_en"}, key_field="slug")
    assert (_revisions(db), _imports(db)) == before


def test_listing_and_reading_imports(db: Db) -> None:
    first = _upload(db, _csv("slug,name,scope", "example-a,Example A,Synthetic scope"), "first.csv")
    second = _upload(
        db, _csv("slug,name,scope", "example-b,Example B,Synthetic scope"), "second.csv"
    )
    one = _run(db, first, entity_type="project", mapping=MAPPING_NO_STATUS).import_run
    two = _run(db, second, entity_type="project", mapping=MAPPING_NO_STATUS).import_run
    with db.session() as session:
        items, total = list_imports(session, offset=0, limit=10)
        assert total == 2
        assert [item["id"] for item in items] == [two["id"], one["id"]]
        assert get_import(session, one["id"]) == one
        with pytest.raises(NotFoundError):
            get_import(session, "imp_unknown")


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (None, None),
        ({"locked": False, "by": "collector:example"}, None),
        ({"locked": True, "by": "import:a.csv#1", "verified": "unverified"}, None),
        ({"locked": True, "by": "import:a.csv#1", "verified": "verified"}, "verified"),
        ({"locked": True, "by": "import:a.csv#1", "restored_from_version": 2}, "restored"),
        ({"locked": True, "by": "user", "verified": "disputed"}, "verified"),
        ({"locked": True, "by": "seed", "src": "seed"}, "seed"),
        ({"locked": True, "by": "user", "src": "manual"}, "manual"),
        ({"locked": True, "by": "user", "src": "collector:example@run_x"}, "manual"),
    ],
)
def test_conflict_reason(entry: dict[str, Any] | None, reason: str | None) -> None:
    assert conflict_reason(entry) == reason
