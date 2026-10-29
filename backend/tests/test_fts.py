"""Full-text index maintenance and query building (DATA_MODEL §10)."""

from __future__ import annotations

import pytest
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from mdt.db.models import DocumentText, SearchKey
from mdt.db.session import read_transaction, write_transaction
from mdt.domain import fts
from mdt.domain.actor import Actor
from mdt.domain.errors import ValidationError
from mdt.domain.revisions import apply_change, soft_delete, undelete
from tests.conftest import Db
from tests.helpers import ALICE, create_project, fts_row

RIGHT_QUOTE = "\N{RIGHT SINGLE QUOTATION MARK}"
MODIFIER = "\N{MODIFIER LETTER APOSTROPHE}"


def search(session: Session, q: str, table: str = "fts_entity") -> set[str]:
    """IDs of the entities whose FTS row matches ``q``."""
    expression = fts.build_match_query(q)
    if expression is None:
        return set()
    with read_transaction(session):
        rows = session.execute(
            text(
                f"SELECT search_key.entity_id FROM {table} "
                f"JOIN search_key ON search_key.rowid = {table}.rowid "
                f"WHERE {table} MATCH :q"
            ),
            {"q": expression},
        )
        return {row[0] for row in rows}


# --------------------------------------------------------------------------------------
# Index maintenance
# --------------------------------------------------------------------------------------


def test_entity_body_contains_the_searchable_fields(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(
            session,
            slug="example-body",
            name_en="Example Body",
            name_uk=f"Приклад з{RIGHT_QUOTE}явився",
            aliases=[{"text": "Alias Text", "lang": "en"}],
            official_urls=["https://example.org/listed"],
            description_en="Line one\nline two",
            status="active",
        ).entity_id
        row = fts_row(session, project_id)
        assert row is not None
        body = row[0]
        for expected in (
            "example-body",
            "Example Body",
            f"з{MODIFIER}явився",
            "Alias Text",
            "https://example.org/listed",
            "Line one\nline two",
        ):
            assert expected in body
        assert RIGHT_QUOTE not in body
        assert "active" not in body  # vocabulary codes are not text


def test_index_follows_updates_deletes_and_undeletes(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Original wording").entity_id
        assert search(session, "Original") == {project_id}
        apply_change(
            session,
            "project",
            project_id,
            {"name_en": "Replaced wording"},
            ALICE,
            expected_version=1,
        )
        assert search(session, "Original") == set()
        assert search(session, "Replaced") == {project_id}
        soft_delete(session, "project", project_id, ALICE, expected_version=2)
        # Deleted entities stay searchable (the trash); queries filter on deleted_at.
        assert search(session, "Replaced") == {project_id}
        undelete(session, "project", project_id, ALICE, expected_version=3)
        assert search(session, "Replaced") == {project_id}
        with read_transaction(session):
            keys = session.execute(
                text("SELECT count(*) FROM search_key WHERE entity_id = :id"), {"id": project_id}
            ).scalar()
            rows = session.execute(text("SELECT count(*) FROM fts_entity")).scalar()
            entities = session.execute(text("SELECT count(*) FROM search_key")).scalar()
        assert keys == 1 and rows == entities


def test_search_keys_are_stable(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session).entity_id
        with read_transaction(session):
            before = session.execute(
                text("SELECT rowid FROM search_key WHERE entity_id = :id"), {"id": project_id}
            ).scalar()
        apply_change(session, "project", project_id, {"name_en": "x"}, ALICE, expected_version=1)
        with read_transaction(session):
            after = session.execute(
                text("SELECT rowid FROM search_key WHERE entity_id = :id"), {"id": project_id}
            ).scalar()
        assert before == after


def test_document_title_and_text(db: Db) -> None:
    collector = Actor.collector("example", "run_01")
    with db.session() as session:
        with write_transaction(session):
            session.execute(
                insert(DocumentText).values(
                    text_hash="hash-1",
                    text=f"Повний текст з{RIGHT_QUOTE}явився тут.",
                    char_count=26,
                    created_at="2026-10-28T10:00:00.000000Z",
                )
            )
        document_id = apply_change(
            session,
            "document",
            None,
            {"title": "Example title", "title_en": "English title", "text_hash": "hash-1"},
            collector,
        ).entity_id
        title, body = fts_row(session, document_id, "fts_document") or ("", "")
        assert title == "Example title\nEnglish title"
        assert body == f"Повний текст з{MODIFIER}явився тут."
        assert search(session, f"з{RIGHT_QUOTE}явився", "fts_document") == {document_id}
        entity_body = (fts_row(session, document_id) or ("",))[0]
        assert "Повний" not in entity_body  # the full text is not part of fts_entity


def test_reindex_rebuilds_both_tables(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Reindexed example").entity_id
        with write_transaction(session):
            session.execute(text("DELETE FROM fts_entity"))
            session.execute(insert(SearchKey).values(entity_id="prj_gone", entity_type="project"))
        assert search(session, "Reindexed") == set()
        with write_transaction(session):
            count = fts.reindex_all(session)
        assert count > 0
        assert search(session, "Reindexed") == {project_id}
        with read_transaction(session):
            assert (
                session.execute(
                    text("SELECT count(*) FROM search_key WHERE entity_id = 'prj_gone'")
                ).scalar()
                == 0
            )


# --------------------------------------------------------------------------------------
# Query building
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("diia", '"diia"*'),
        ("  Приклад   Тест ", '"Приклад"* AND "Тест"*'),
        ('"Приклад Тест" зразок', '"Приклад Тест" AND "зразок"*'),
        ('say "hi', '"say"* AND """hi"*'),
        ("a-b", '"a-b"*'),
        ("- . \N{EN DASH} *", None),
        ("", None),
        ('""', None),
        ("AND OR NOT", '"AND"* AND "OR"* AND "NOT"*'),
        ("title:secret", '"title:secret"*'),
        (f"з{RIGHT_QUOTE}явився", f'"з{MODIFIER}явився"*'),
    ],
)
def test_build_match_query(q: str, expected: str | None) -> None:
    assert fts.build_match_query(q) == expected


def test_query_limits() -> None:
    assert fts.build_match_query("x" * 200) is not None
    with pytest.raises(ValidationError):
        fts.build_match_query("x" * 201)
    assert fts.build_match_query(" ".join(["w"] * 16)) is not None
    with pytest.raises(ValidationError):
        fts.build_match_query(" ".join(["w"] * 17))
    # Dropped punctuation tokens do not count.
    assert fts.build_match_query(" ".join(["w"] * 16 + ["-"] * 5)) is not None


def test_matching_is_prefix_case_insensitive_and_cyrillic(db: Db) -> None:
    with db.session() as session:
        first = create_project(session, name_en=None, name_uk="Приклад.Тест").entity_id
        second = create_project(session, name_en=None, name_uk="Зразок").entity_id
        third = create_project(session, name_en="Example punctuation - test").entity_id
        assert search(session, "приклад") == {first}
        assert search(session, "ТЕС") == {first}
        assert search(session, "при тес") == {first}
        assert search(session, '"Приклад Тест"') == {first}
        assert search(session, "зра") == {second}
        assert search(session, "punctuation - test") == {third}
        assert search(session, "-") == set()
        assert search(session, "nothing-like-this") == set()
