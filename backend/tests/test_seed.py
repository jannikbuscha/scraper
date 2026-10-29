"""The idempotent seed (DATA_MODEL §9) on synthetic data and on the real files."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mdt.config import REPO_ROOT
from mdt.db.migrate import upgrade_database
from mdt.db.models import Organization, Project, Revision, Vocabulary, VocabularyTerm
from mdt.db.session import read_transaction
from mdt.domain.check import run_check
from mdt.domain.revisions import apply_change, restore_version, set_field_verification, soft_delete
from mdt.domain.seed import SeedFileError, load_seed_file, run_seed
from mdt.domain.vocab import TermIndex
from tests import synthetic
from tests.conftest import Db, make_settings, open_db
from tests.helpers import ALICE, create_evidence, load, revision_count, revisions_of

SEED_PROJECTS: list[dict[str, Any]] = [
    {
        "slug": "example-one",
        "name_en": "Example One",
        "name_uk": "Приклад один",
        "paper_cluster": "cluster_a",
        "in_paper_scope": True,
        "scope_note": "Synthetic scope note.",
        "ministry_urls": ["https://example.org/projects/one"],
        "official_urls": [],
        "aliases": [{"text": "Example One", "lang": "en", "case_sensitive": True, "kind": "name"}],
    },
    {
        "slug": "example-two",
        "name_en": "Example Two",
        "name_uk": None,
        "paper_cluster": None,
        "in_paper_scope": False,
        "scope_note": "Synthetic reason for exclusion.",
        "ministry_urls": [],
        "official_urls": ["https://example.org/two"],
        "aliases": [],
    },
]


def seeded_db(db: Db, tmp_path: Path, projects: list[dict[str, Any]]) -> Db:
    """The test database with settings pointing at a seed file with ``projects``."""
    seed_dir = synthetic.write_seed(tmp_path / "seed", projects)
    return open_db(db.root, make_settings(db.root, db.settings.codebook_path, seed_dir))


def project_id_by_key(session: Session, key: str) -> str:
    with read_transaction(session):
        return str(session.execute(select(Project.id).where(Project.seed_key == key)).scalar_one())


@pytest.fixture
def seeded(db: Db, tmp_path: Path) -> Any:
    database = seeded_db(db, tmp_path, SEED_PROJECTS)
    with database.session() as session:
        report = run_seed(session, database.settings)
    assert not report.errors, report.errors
    yield database
    database.engine.dispose()


# --------------------------------------------------------------------------------------
# Synthetic seed
# --------------------------------------------------------------------------------------


def test_seed_creates_projects_with_seed_provenance(seeded: Db) -> None:
    with seeded.session() as session:
        project_id = project_id_by_key(session, "example-two")
        row = load(session, "project", project_id)
        assert (row["slug"], row["seed_key"], row["created_by"]) == (
            "example-two",
            "example-two",
            "seed",
        )
        # Empty seed values are "not provided": no entry, no lock.
        assert set(row["field_meta"]) == {
            "slug",
            "name_en",
            "in_paper_scope",
            "scope_note",
            "official_urls",
        }
        assert row["field_meta"]["name_en"]["src"] == "seed"
        assert row["field_meta"]["name_en"]["locked"] is True
        [revision] = revisions_of(session, project_id)
        assert (revision.channel, revision.author, revision.note) == (
            "seed",
            "seed",
            "Synthetic test seed",
        )
        term = TermIndex(session).term("status", "active")
        session.rollback()
        assert term is not None
        [term_revision] = revisions_of(session, term.id)
        assert term_revision.note == "Loaded from codebook/status.yaml"


def test_second_run_writes_nothing(seeded: Db) -> None:
    with seeded.session() as session:
        before = revision_count(session)
        report = run_seed(session, seeded.settings)
        assert revision_count(session) == before
        assert report.revisions == 0 and not report.drift and not report.errors
        assert report.unchanged["project"] == 2
        assert report.unchanged["vocabulary_term"] == sum(
            len(terms) for _, _, terms in synthetic.VOCABULARIES.values()
        )
        assert report.vocabularies_created == report.vocabularies_updated == 0
        assert not report.derived_recomputed


def test_human_edits_and_clears_are_never_overwritten(seeded: Db) -> None:
    with seeded.session() as session:
        project_id = project_id_by_key(session, "example-one")
        apply_change(
            session,
            "project",
            project_id,
            {"name_en": "Edited by a person", "name_uk": None},
            ALICE,
            expected_version=1,
        )
        report = run_seed(session, seeded.settings)
        row = load(session, "project", project_id)
        assert (row["name_en"], row["name_uk"], row["version"]) == ("Edited by a person", None, 2)
        assert report.revisions == 0
        assert sorted((line.field, line.current, line.seed) for line in report.drift) == [
            ("name_en", "Edited by a person", "Example One"),
            ("name_uk", None, "Приклад один"),
        ]
        assert "seed drift: project example-one" in str(report.drift[0])


def test_verified_or_restored_seed_values_are_protected(seeded: Db, tmp_path: Path) -> None:
    with seeded.session() as session:
        one = project_id_by_key(session, "example-one")
        two = project_id_by_key(session, "example-two")
        evidence_id = create_evidence(session, one, "name_en").entity_id
        set_field_verification(
            session,
            "project",
            one,
            "name_en",
            "verified",
            ALICE,
            evidence_id=evidence_id,
            expected_version=1,
        )
        apply_change(session, "project", two, {"name_en": "Temporary"}, ALICE, expected_version=1)
        restore_version(session, "project", two, 1, ALICE, expected_version=2)
        assert load(session, "project", two)["field_meta"]["name_en"]["restored_from_version"] == 1
    changed = [
        {**SEED_PROJECTS[0], "name_en": "Seed changed one"},
        {**SEED_PROJECTS[1], "name_en": "Seed changed two"},
    ]
    database = seeded_db(seeded, tmp_path / "changed", changed)
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert {line.field for line in report.drift} == {"name_en"}
            assert len(report.drift) == 2
            assert load(session, "project", one)["name_en"] == "Example One"
            assert load(session, "project", two)["name_en"] == "Example Two"
    finally:
        database.engine.dispose()


def test_seed_updates_its_own_and_unset_fields(seeded: Db, tmp_path: Path) -> None:
    changed = [
        {**SEED_PROJECTS[0], "name_en": "Renamed in the seed", "status": "active"},
        SEED_PROJECTS[1],
    ]
    database = seeded_db(seeded, tmp_path / "changed", changed)
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert (report.updated["project"], report.unchanged["project"], report.revisions) == (
                1,
                1,
                1,
            )
            project_id = project_id_by_key(session, "example-one")
            row = load(session, "project", project_id)
            assert (row["name_en"], row["status"], row["version"]) == (
                "Renamed in the seed",
                "active",
                2,
            )
            assert row["field_meta"]["status"]["src"] == "seed"
            # A value removed from the seed file is "not provided" and stays.
            removed = [{**changed[0], "name_uk": None}, SEED_PROJECTS[1]]
            again = seeded_db(seeded, tmp_path / "removed", removed)
            try:
                with again.session() as other:
                    assert run_seed(other, again.settings).revisions == 0
                    assert load(other, "project", project_id)["name_uk"] == "Приклад один"
            finally:
                again.engine.dispose()
    finally:
        database.engine.dispose()


def test_scope_change_from_the_seed_keeps_the_rule(seeded: Db, tmp_path: Path) -> None:
    changed = [SEED_PROJECTS[0], {**SEED_PROJECTS[1], "in_paper_scope": True}]
    database = seeded_db(seeded, tmp_path / "changed", changed)
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert not report.errors and report.revisions == 1
            project_id = project_id_by_key(session, "example-two")
            assert load(session, "project", project_id)["in_paper_scope"] == 1
    finally:
        database.engine.dispose()


def test_deleted_rows_are_skipped_and_renamed_slugs_do_not_duplicate(
    seeded: Db, tmp_path: Path
) -> None:
    with seeded.session() as session:
        one = project_id_by_key(session, "example-one")
        two = project_id_by_key(session, "example-two")
        soft_delete(session, "project", one, ALICE, expected_version=1)
        apply_change(
            session, "project", two, {"slug": "example-renamed"}, ALICE, expected_version=1
        )
    changed = [{**SEED_PROJECTS[0], "name_en": "Changed"}, SEED_PROJECTS[1]]
    database = seeded_db(seeded, tmp_path / "changed", changed)
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert report.skipped_deleted["project"] == 1
            assert report.created["project"] == 0 and report.revisions == 0
            assert [line.field for line in report.drift] == ["slug"]
            row = load(session, "project", one)
            assert row["deleted_at"] is not None and row["name_en"] == "Example One"
            with read_transaction(session):
                assert session.execute(select(func.count()).select_from(Project)).scalar() == 2
    finally:
        database.engine.dispose()


def test_dry_run_writes_nothing(db: Db, tmp_path: Path) -> None:
    database = seeded_db(db, tmp_path, SEED_PROJECTS)
    try:
        with database.session() as session:
            before = revision_count(session)
            report = run_seed(session, database.settings, dry_run=True)
            assert report.created["project"] == 2 and report.dry_run
            assert revision_count(session) == before
            assert "project: would create 2" in "\n".join(report.lines())
            with read_transaction(session):
                assert session.execute(select(func.count()).select_from(Project)).scalar() == 0
    finally:
        database.engine.dispose()


def test_vocabulary_metadata_is_updated_without_revisions(db: Db, tmp_path: Path) -> None:
    codebook = tmp_path / "codebook"
    shutil.copytree(db.settings.codebook_path, codebook)
    path = codebook / "status.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["label"] = "Example status, relabelled"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    database = open_db(db.root, make_settings(db.root, codebook, db.settings.seed_path))
    try:
        with database.session() as session:
            before = revision_count(session)
            report = run_seed(session, database.settings)
            assert report.vocabularies_updated == 1 and report.revisions == 0
            assert revision_count(session) == before
            with read_transaction(session):
                vocabulary = session.get(Vocabulary, "status")
                assert vocabulary is not None
                assert vocabulary.label == "Example status, relabelled"
    finally:
        database.engine.dispose()


def rewrite_definitions(codebook: Path, definitions: dict[tuple[str, str], str]) -> None:
    """Change term definitions, by (vocabulary, code), in the files of ``codebook``."""
    for (name, code), definition in definitions.items():
        path = codebook / f"{name}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        next(term for term in data["terms"] if term["code"] == code)["definition"] = definition
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_corrected_definitions_reach_an_existing_database(db: Db, tmp_path: Path) -> None:
    # A definition corrected in codebook/*.yaml reaches a seeded database on the next run as a
    # term revision; a definition that a person edited in the app is kept and reported as drift.
    with db.session() as session:
        index = TermIndex(session)
        unknown = index.term("period", "unknown")
        conflicting = index.term("derived_reason", "conflicting_dates")
        session.rollback()
        assert unknown is not None and conflicting is not None
        apply_change(
            session,
            "vocabulary_term",
            conflicting.id,
            {"definition": "Edited by a person."},
            ALICE,
            expected_version=1,
        )
    codebook = tmp_path / "codebook"
    shutil.copytree(db.settings.codebook_path, codebook)
    rewrite_definitions(
        codebook,
        {
            ("period", "unknown"): "Corrected in the file.",
            ("derived_reason", "conflicting_dates"): "Also corrected in the file.",
        },
    )
    database = open_db(db.root, make_settings(db.root, codebook, db.settings.seed_path))
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert not report.errors, report.errors
            assert (report.updated["vocabulary_term"], report.revisions) == (1, 1)
            assert report.vocabularies_updated == 0
            assert [(line.key, line.field, line.current, line.seed) for line in report.drift] == [
                (
                    "derived_reason:conflicting_dates",
                    "definition",
                    "Edited by a person.",
                    "Also corrected in the file.",
                )
            ]
            row = load(session, "vocabulary_term", unknown.id)
            assert (row["definition"], row["version"]) == ("Corrected in the file.", 2)
            assert row["field_meta"]["definition"]["src"] == "seed"
            revision = revisions_of(session, unknown.id)[-1]
            assert (revision.channel, revision.author, revision.note) == (
                "seed",
                "seed",
                "Loaded from codebook/period.yaml",
            )
            edited = load(session, "vocabulary_term", conflicting.id)
            assert (edited["definition"], edited["version"]) == ("Edited by a person.", 2)
            again = run_seed(session, database.settings)
            assert again.revisions == 0 and len(again.drift) == 1
    finally:
        database.engine.dispose()


def test_invalid_entries_are_reported(db: Db, tmp_path: Path) -> None:
    database = seeded_db(db, tmp_path, [{**SEED_PROJECTS[0], "ministry_urls": ["ftp://x"]}])
    try:
        with database.session() as session:
            report = run_seed(session, database.settings)
            assert len(report.errors) == 1 and "example-one" in report.errors[0]
            assert any(line.startswith("error:") for line in report.lines())
    finally:
        database.engine.dispose()


def test_seed_file_checks(tmp_path: Path) -> None:
    path = tmp_path / "projects.yaml"
    for content, message in (
        ("- just a list\n", "expected a mapping"),
        ("projects: {slug: x}\n", "must be a list of mappings"),
        ("projects:\n  - name_en: No slug\n", "needs a slug"),
        ("projects:\n  - {slug: x, unicorn: 1}\n", "unknown fields"),
        ("projects: [\n", "cannot read"),
    ):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(SeedFileError, match=message):
            load_seed_file(path)
    with pytest.raises(SeedFileError, match="cannot read"):
        load_seed_file(tmp_path / "missing.yaml")


# --------------------------------------------------------------------------------------
# The real codebook and seed files
# --------------------------------------------------------------------------------------


def test_seed_with_the_real_files(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        REPO_ROOT / "codebook",
        REPO_ROOT / "seed",
        focal_org_seed_key="ministry-of-digital-transformation",
    )
    upgrade_database(settings.sqlalchemy_url)
    database = open_db(tmp_path, settings)
    try:
        with database.session() as session:
            report = run_seed(session, settings)
            assert not report.errors, report.errors
            assert report.vocabularies_created == 26
            assert report.created == {"vocabulary_term": 175, "organization": 1, "project": 20}
            assert report.revisions == 196
            assert report.derived_recomputed
            with read_transaction(session):
                count = session.execute(select(func.count()).select_from(VocabularyTerm)).scalar()
                assert count == 175
                projects = session.scalars(select(Project)).all()
                assert len(projects) == 20
                assert sum(1 for p in projects if p.in_paper_scope) == 19
                assert sum(1 for p in projects if p.name_uk is None) == 9
                outside = next(p for p in projects if p.seed_key == "european-integration")
                assert (outside.in_paper_scope, outside.paper_cluster) == (False, None)
                assert all(p.ministry_categories == [] for p in projects)
                assert all(p.field_meta["slug"]["src"] == "seed" for p in projects)
                assert all("name_uk" not in p.field_meta for p in projects if p.name_uk is None)
                organizations = session.scalars(select(Organization)).all()
                assert [o.seed_key for o in organizations] == ["ministry-of-digital-transformation"]
                notes = set(
                    session.scalars(
                        select(Revision.note).where(Revision.entity_type == "project")
                    ).all()
                )
                [note] = notes
                assert note is not None and note.startswith("Assignment §3")
            second = run_seed(session, settings)
            assert second.revisions == 0 and not second.drift and not second.errors
            assert second.unchanged == {"vocabulary_term": 175, "organization": 1, "project": 20}
            assert run_check(session, settings).ok
    finally:
        database.engine.dispose()
