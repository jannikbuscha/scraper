"""Full-text index maintenance and query building (DATA_MODEL §10)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from mdt.db.models import DocumentText, SearchKey
from mdt.db.session import read_transaction, write_transaction
from mdt.domain import fts
from mdt.domain.actor import Actor
from mdt.domain.revisions import apply_change, soft_delete, undelete
from tests.conftest import Db
from tests.helpers import USER, create_project, fts_row

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
            USER,
        )
        assert search(session, "Original") == set()
        assert search(session, "Replaced") == {project_id}
        soft_delete(session, "project", project_id, USER)
        # Deleted entities stay searchable (the trash); queries filter on deleted_at.
        assert search(session, "Replaced") == {project_id}
        undelete(session, "project", project_id, USER)
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
        apply_change(session, "project", project_id, {"name_en": "x"}, USER)
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


def _fts_rowids(session: Session, table: str) -> set[int]:
    with read_transaction(session):
        return {int(r[0]) for r in session.execute(text(f"SELECT rowid FROM {table}"))}


def test_reindex_runs_in_batches_and_removes_orphaned_rows(db: Db) -> None:
    with db.session() as session:
        names = [f"Batched example {index}" for index in range(7)]
        ids = {create_project(session, name_en=name).entity_id for name in names}
        with write_transaction(session):
            # stale content, an orphaned fts_entity row and a document row of a project
            session.execute(text("UPDATE fts_entity SET body = 'stale' WHERE rowid > 0"))
            session.execute(text("INSERT INTO fts_entity(rowid, body) VALUES (999999, 'gone')"))
            project_rowid = session.execute(
                select(SearchKey.rowid).where(SearchKey.entity_id == next(iter(ids)))
            ).scalar_one()
            session.execute(
                text("INSERT INTO fts_document(rowid, title, body) VALUES (:r, 'x', 'y')"),
                {"r": project_rowid},
            )
        units: list[bool] = []
        original = fts.write_transaction

        def counting(session_: Session) -> Any:
            units.append(True)
            return original(session_)

        with patch.object(fts, "write_transaction", counting):
            count = fts.reindex_all(session, batch_size=3)
        assert count >= len(ids)
        # one unit per batch of at most 3 records per type, plus the orphan clean-up
        assert len(units) > count // 3
        assert search(session, "Batched example") == ids
        assert search(session, "stale") == set()
        assert 999999 not in _fts_rowids(session, "fts_entity")
        assert project_rowid not in _fts_rowids(session, "fts_document")


def test_reindex_releases_the_write_lock_between_batches(db: Db) -> None:
    # `mdt reindex` used to hold one write transaction for the whole rebuild, so UI
    # writes failed after the busy timeout. Now another connection can write between
    # any two batches without waiting (it would block for 10 s and fail otherwise).
    with db.session() as session:
        for index in range(5):
            create_project(session, name_en=f"Concurrent example {index}")
        other = db.session()
        written: list[str] = []
        original = fts.write_transaction

        def between_batches(session_: Session) -> Any:
            assert not session_.in_transaction()
            name = f"Written during reindex {len(written)}"
            written.append(create_project(other, name_en=name).entity_id)
            return original(session_)

        try:
            with patch.object(fts, "write_transaction", between_batches):
                fts.reindex_all(session, batch_size=2)
        finally:
            other.close()
        assert len(written) > 3
        assert search(session, "Written during reindex") == set(written)


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
        # tabs and line breaks separate tokens, also inside phrases
        ("a\tb\nc", '"a"* AND "b"* AND "c"*'),
        ('"a\tb"', '"a b"'),
    ],
)
def test_build_match_query(q: str, expected: str | None) -> None:
    assert fts.build_match_query(q) == expected


def test_long_queries_are_searched(db: Db) -> None:
    with db.session() as session:
        project_id = create_project(session, name_en="Zqxj Wvut Kplm").entity_id
        assert search(session, " ".join(["zqxj"] * 40)) == {project_id}
        assert search(session, "zqxj " + "x" * 300) == set()


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
