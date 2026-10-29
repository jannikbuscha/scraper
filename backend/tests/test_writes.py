"""The one write path: apply_change create, update and no-op (DATA_MODEL §5, §6.1-§6.3)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from mdt.db.models import Derived
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.errors import (
    ConflictError,
    EntityDeletedError,
    LockedFieldError,
    NotFoundError,
    ValidationError,
)
from mdt.domain.revisions import apply_change, soft_delete
from tests.conftest import Db
from tests.helpers import (
    ALICE,
    BOB,
    assert_matches_latest_snapshot,
    create_project,
    fields_of,
    fts_row,
    load,
    project_data,
    revisions_of,
)

COLLECTOR = Actor.collector("example", "run_01")


def entry(src: str, by: str, at: str, *, locked: bool = True) -> dict[str, object]:
    return {
        "src": src,
        "by": by,
        "at": at,
        "locked": locked,
        "verified": "unverified",
        "evidence_id": None,
        "restored_from_version": None,
    }


# --------------------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------------------


def test_create_writes_row_revision_meta_derived_and_fts(db: Db) -> None:
    with db.session() as session:
        result = apply_change(
            session,
            "project",
            None,
            project_data(slug="example-a", name_uk="Приклад", policy_domains=None),
            ALICE,
            note="Created for a test",
        )
        assert result.changed and result.version == 1 and result.revision_id is not None
        row = load(session, "project", result.entity_id)
        assert result.entity_id.startswith("prj_")
        ts = row["created_at"]
        assert (row["version"], row["created_by"], row["updated_by"]) == (1, ALICE.by, ALICE.by)
        assert row["updated_at"] == ts
        assert row["policy_domains"] == []
        # Entries only for provided non-empty fields; all with the unit's timestamp.
        manual = entry("manual:Alice Example", "Alice Example", ts)
        assert row["field_meta"] == {
            "slug": manual,
            "name_en": manual,
            "name_uk": manual,
            "scope_note": manual,
        }
        [revision] = revisions_of(session, result.entity_id)
        assert (revision.version, revision.action, revision.channel, revision.author) == (
            1,
            "create",
            "ui",
            ALICE.by,
        )
        assert revision.at == ts and revision.note == "Created for a test"
        assert revision.id == result.revision_id
        assert revision.schema_revision is not None
        # Non-empty fields of the new state, defaults and False included.
        assert revision.diff == {
            "fields": {
                "slug": [None, "example-a"],
                "name_en": [None, "Example project"],
                "name_uk": [None, "Приклад"],
                "in_paper_scope": [None, False],
                "scope_note": [None, "Synthetic scope note."],
                "verification_status": [None, "unverified"],
            }
        }
        assert revision.snapshot["state"] == {
            "deleted_at": None,
            "deleted_by": None,
            "merged_into": None,
        }
        assert revision.snapshot == result.snapshot
        with read_transaction(session):
            derived = session.get(Derived, result.entity_id)
            assert derived is not None
            assert (derived.period, derived.period_reason) == ("unknown", "no_date")
            assert (derived.war_trajectory, derived.trajectory_reason) == ("unknown", "no_date")
            assert derived.existed_before_invasion is False
        row_body = fts_row(session, result.entity_id)
        assert row_body is not None
        assert "Приклад" in row_body[0] and "example-a" in row_body[0]
    assert_matches_latest_snapshot(db, "project", result.entity_id)


def test_create_with_empty_values_records_no_meta(db: Db) -> None:
    with db.session() as session:
        result = create_project(session, name_uk="", official_urls=[], notes="  ")
        row = load(session, "project", result.entity_id)
        assert set(row["field_meta"]) == {"slug", "name_en", "scope_note"}
        assert row["name_uk"] is None and row["notes"] is None


def test_unknown_type_is_not_found(db: Db) -> None:
    with db.session() as session, pytest.raises(NotFoundError):
        apply_change(session, "unicorn", None, {}, ALICE)


def test_update_of_missing_row_is_not_found(db: Db) -> None:
    with db.session() as session, pytest.raises(NotFoundError):
        apply_change(
            session, "project", "prj_01JBX3ABCDEFGHJKMNPQRSTVWX", {}, ALICE, expected_version=1
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("unicorn", 1, "is not a field of this entity type"),
        ("launch", "2020", "is derived and cannot be set"),
        ("open_comments", 1, "is computed and cannot be set"),
        ("created_at", "2026-01-01T00:00:00.000000Z", "is computed and cannot be set"),
        ("version", 7, "is computed and cannot be set"),
        ("seed_key", "example", "cannot be set"),
    ],
)
def test_fields_clients_cannot_write(db: Db, field: str, value: object, message: str) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        apply_change(session, "project", None, project_data(**{field: value}), ALICE)
    assert caught.value.details == {field: [message]}


def test_system_and_computed_document_fields_are_refused_from_clients(db: Db) -> None:
    data = {"title": "Example document", "canonical_url": "https://example.org"}
    with db.session() as session, pytest.raises(ValidationError) as caught:
        apply_change(session, "document", None, {**data, "text_hash": "abc"}, ALICE)
    assert caught.value.details == {
        "canonical_url": ["is computed and cannot be set"],
        "text_hash": ["is set by the system"],
    }


def test_changes_must_be_an_object(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError):
        apply_change(session, "project", None, ["slug"], ALICE)  # type: ignore[arg-type]


def test_note_longer_than_2000_characters_is_refused(db: Db) -> None:
    with db.session() as session, pytest.raises(ValidationError) as caught:
        apply_change(session, "project", None, project_data(), ALICE, note="n" * 2001)
    assert "note" in (caught.value.details or {})


# --------------------------------------------------------------------------------------
# Update and no-op
# --------------------------------------------------------------------------------------


def test_update_writes_a_revision_with_field_and_meta_diff(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
        result = apply_change(
            session,
            "project",
            created.entity_id,
            {"name_en": "Renamed example", "status": "active"},
            BOB,
            note="Renamed",
            expected_version=1,
        )
        assert result.changed and result.version == 2
        row = load(session, "project", created.entity_id)
        assert (row["version"], row["updated_by"], row["created_by"]) == (2, BOB.by, ALICE.by)
        ts = row["updated_at"]
        assert row["field_meta"]["name_en"] == entry("manual:Bob Example", "Bob Example", ts)
        assert row["field_meta"]["status"] == entry("manual:Bob Example", "Bob Example", ts)
        assert row["field_meta"]["slug"]["by"] == ALICE.by
        revision = revisions_of(session, created.entity_id)[-1]
        assert (revision.version, revision.action, revision.note, revision.at) == (
            2,
            "update",
            "Renamed",
            ts,
        )
        assert revision.diff["fields"] == {
            "name_en": ["Example project", "Renamed example"],
            "status": [None, "active"],
        }
        assert revision.diff["meta"] == {
            "name_en": {
                "src": ["manual:Alice Example", "manual:Bob Example"],
                "by": [ALICE.by, BOB.by],
            },
            "status": {
                "src": [None, "manual:Bob Example"],
                "by": [None, BOB.by],
                "locked": [None, True],
                "verified": [None, "unverified"],
            },
        }
        assert "state" not in revision.diff
    assert_matches_latest_snapshot(db, "project", created.entity_id)


def test_no_op_writes_nothing(db: Db) -> None:
    with db.session() as session:
        created = create_project(session, policy_domains=["domain_a", "domain_b"])
        before = load(session, "project", created.entity_id)
        result = apply_change(
            session,
            "project",
            created.entity_id,
            {
                "name_en": "  Example project ",
                "policy_domains": ["domain_a", "domain_b", "domain_a"],
                "official_urls": None,
                "name_uk": "",
            },
            ALICE,
            expected_version=1,
        )
        assert (result.changed, result.version, result.revision_id) == (False, 1, None)
        assert load(session, "project", created.entity_id) == before
        assert len(revisions_of(session, created.entity_id)) == 1


def test_reordering_a_list_is_a_change(db: Db) -> None:
    with db.session() as session:
        created = create_project(session, policy_domains=["domain_a", "domain_b"])
        result = apply_change(
            session,
            "project",
            created.entity_id,
            {"policy_domains": ["domain_b", "domain_a"]},
            ALICE,
            expected_version=1,
        )
        assert result.changed
        assert fields_of(session, "project", created.entity_id)["policy_domains"] == [
            "domain_b",
            "domain_a",
        ]


def test_null_and_empty_list_are_the_same_value(db: Db) -> None:
    with db.session() as session:
        created = create_project(session, policy_domains=["domain_a"])
        cleared = apply_change(
            session,
            "project",
            created.entity_id,
            {"policy_domains": None},
            ALICE,
            expected_version=1,
        )
        assert cleared.changed
        row = load(session, "project", created.entity_id)
        assert row["policy_domains"] == []
        again = apply_change(
            session, "project", created.entity_id, {"policy_domains": []}, ALICE, expected_version=2
        )
        assert not again.changed


def test_clearing_a_field_keeps_and_updates_its_entry(db: Db) -> None:
    with db.session() as session:
        created = create_project(session, name_uk="Приклад")
        apply_change(
            session, "project", created.entity_id, {"name_uk": None}, BOB, expected_version=1
        )
        row = load(session, "project", created.entity_id)
        assert row["name_uk"] is None
        assert row["field_meta"]["name_uk"]["by"] == BOB.by
    assert_matches_latest_snapshot(db, "project", created.entity_id)


def test_expected_version_is_required_on_channel_ui(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
        with pytest.raises(ValidationError) as caught:
            apply_change(session, "project", created.entity_id, {"name_en": "x"}, ALICE)
        assert caught.value.details == {"expected_version": ["is required"]}
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "project",
                created.entity_id,
                {"name_en": "x"},
                ALICE,
                expected_version="1",  # type: ignore[arg-type]
            )


def test_stale_version_is_a_conflict_even_without_differences(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
        apply_change(
            session, "project", created.entity_id, {"status": "active"}, BOB, expected_version=1
        )
        with pytest.raises(ConflictError):
            apply_change(
                session,
                "project",
                created.entity_id,
                {"status": "active"},
                ALICE,
                expected_version=1,
            )


def test_writes_to_deleted_rows_are_refused(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
        soft_delete(session, "project", created.entity_id, ALICE, expected_version=1)
        with pytest.raises(EntityDeletedError) as caught:
            apply_change(
                session, "project", created.entity_id, {"name_en": "x"}, ALICE, expected_version=2
            )
        details = caught.value.details or {}
        assert details["deleted_by"] == ALICE.by and details["deleted_at"]


def test_older_snapshots_are_never_modified(db: Db) -> None:
    with db.session() as session:
        created = create_project(session, aliases=[{"text": "Example", "lang": "en"}])
        apply_change(
            session,
            "project",
            created.entity_id,
            {"aliases": [{"text": "Example", "lang": "en"}, {"text": "Second", "lang": "en"}]},
            ALICE,
            expected_version=1,
        )
        first, second = revisions_of(session, created.entity_id)
        assert first.snapshot == created.snapshot
        assert len(first.snapshot["fields"]["aliases"]) == 1
        assert len(second.snapshot["fields"]["aliases"]) == 2


# --------------------------------------------------------------------------------------
# Provenance per channel
# --------------------------------------------------------------------------------------


def test_field_meta_per_machine_channel(db: Db) -> None:
    with db.session() as session:
        seeded = apply_change(session, "project", None, project_data(), Actor.seed())
        imported = apply_change(
            session, "project", None, project_data(), Actor.importer("example.xlsx")
        )
        collected = apply_change(session, "project", None, project_data(), COLLECTOR)
        seed_row = load(session, "project", seeded.entity_id)
        assert seed_row["field_meta"]["slug"] == entry("seed", "seed", seed_row["created_at"])
        assert seed_row["created_by"] == "seed"
        import_row = load(session, "project", imported.entity_id)
        assert import_row["field_meta"]["slug"] == entry(
            "import:example.xlsx", "import:example.xlsx", import_row["created_at"]
        )
        collector_row = load(session, "project", collected.entity_id)
        assert collector_row["field_meta"]["slug"] == entry(
            "collector:example@run_01",
            "collector:example",
            collector_row["created_at"],
            locked=False,
        )
        [revision] = revisions_of(session, collected.entity_id)
        assert (revision.channel, revision.author, revision.run_id) == (
            "collector",
            "collector:example",
            "run_01",
        )


def test_collector_cannot_change_locked_fields(db: Db) -> None:
    with db.session() as session:
        created = apply_change(session, "project", None, project_data(), COLLECTOR)
        # Fields the collector set itself stay unlocked; fields without entry are free.
        updated = apply_change(
            session,
            "project",
            created.entity_id,
            {"name_en": "Collected name", "description_en": "Collected description."},
            COLLECTOR,
        )
        assert updated.changed
        apply_change(
            session,
            "project",
            created.entity_id,
            {"name_en": "Manual name"},
            ALICE,
            expected_version=2,
        )
        with pytest.raises(LockedFieldError) as caught:
            apply_change(
                session,
                "project",
                created.entity_id,
                {"name_en": "Collected again", "description_en": "Changed."},
                COLLECTOR,
            )
        assert caught.value.details == {"fields": ["name_en"]}
        row = load(session, "project", created.entity_id)
        assert (row["name_en"], row["description_en"], row["version"]) == (
            "Manual name",
            "Collected description.",
            3,
        )
        # Seeded values are locked as well.
        seeded = apply_change(session, "project", None, project_data(), Actor.seed())
        with pytest.raises(LockedFieldError):
            apply_change(session, "project", seeded.entity_id, {"name_en": "x"}, COLLECTOR)


def test_collector_may_write_system_fields_clients_may_not(db: Db) -> None:
    with db.session() as session:
        document = apply_change(
            session,
            "document",
            None,
            {"title": "Example document", "source_id": "example_source", "text_hash": "abc"},
            COLLECTOR,
        )
        row = load(session, "document", document.entity_id)
        assert (row["source_id"], row["text_hash"]) == ("example_source", "abc")
        with pytest.raises(ValidationError):
            apply_change(
                session,
                "document",
                document.entity_id,
                {"source_id": "other"},
                ALICE,
                expected_version=1,
            )


# --------------------------------------------------------------------------------------
# Computed system fields
# --------------------------------------------------------------------------------------


def test_canonical_url_follows_url_in_the_same_revision(db: Db) -> None:
    with db.session() as session:
        created = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "url": "https://Example.org/a/?utm_source=x#top",
                "retrieved_at": "2026-10-28T10:00:00Z",
            },
            ALICE,
        )
        row = load(session, "document", created.entity_id)
        assert row["url"] == "https://Example.org/a/?utm_source=x#top"
        assert row["canonical_url"] == "https://example.org/a"
        assert row["field_meta"]["canonical_url"] == row["field_meta"]["url"]
        apply_change(
            session,
            "document",
            created.entity_id,
            {"url": "https://example.org/b"},
            BOB,
            expected_version=1,
        )
        row = load(session, "document", created.entity_id)
        assert row["canonical_url"] == "https://example.org/b"
        assert row["field_meta"]["canonical_url"] == row["field_meta"]["url"]
        assert row["field_meta"]["canonical_url"]["by"] == BOB.by
        revision = revisions_of(session, created.entity_id)[-1]
        assert set(revision.diff["fields"]) == {"url", "canonical_url"}
        apply_change(session, "document", created.entity_id, {"url": None}, BOB, expected_version=2)
        assert load(session, "document", created.entity_id)["canonical_url"] is None
    assert_matches_latest_snapshot(db, "document", created.entity_id)


def test_document_retrieved_at_is_normalised(db: Db) -> None:
    with db.session() as session:
        created = apply_change(
            session,
            "document",
            None,
            {
                "title": "Example document",
                "url": "https://example.org/doc",
                "retrieved_at": "2026-10-28T12:00:00+02:00",
            },
            ALICE,
        )
        assert load(session, "document", created.entity_id)["retrieved_at"] == (
            "2026-10-28T10:00:00.000000Z"
        )


# --------------------------------------------------------------------------------------
# Revision fallback
# --------------------------------------------------------------------------------------


def test_integrity_error_on_revision_version_is_a_conflict(db: Db) -> None:
    with db.session() as session:
        created = create_project(session)
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO revision (entity_type, entity_id, version, at, author, channel,"
                " action, snapshot, diff) VALUES ('project', :id, 2,"
                " '2026-01-01T00:00:00.000000Z', 'Alice Example', 'ui', 'update', '{}', '{}')"
            ),
            {"id": created.entity_id},
        )
    with db.session() as session:
        with pytest.raises(ConflictError) as caught:
            apply_change(
                session, "project", created.entity_id, {"name_en": "x"}, BOB, expected_version=1
            )
        assert caught.value.payload["action"] == "patch"
        # Nothing was written: the row is unchanged.
        row = load(session, "project", created.entity_id)
        assert (row["version"], row["name_en"]) == (1, "Example project")
        with read_transaction(session):
            assert session.execute(select(Derived.entity_id)).scalars().all()
    db.check_on_teardown = False  # the injected revision does not match the row
