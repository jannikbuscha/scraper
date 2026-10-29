"""Helpers for the read-side tests (lists, facets, lookup, feeds, exports).

All values are synthetic. Documents with a full text are written by a collector actor,
because ``text_hash`` is a system field.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mdt.db.models import DocumentText, VocabularyTerm
from mdt.db.session import read_transaction, write_transaction
from mdt.domain.actor import Actor
from mdt.domain.check import run_check
from mdt.domain.clock import utc_now
from mdt.domain.query import list_entities
from mdt.domain.revisions import apply_change
from mdt.domain.writes import ChangeResult
from tests.conftest import Db, make_settings, open_db
from tests.helpers import USER

COLLECTOR = Actor.collector("example", "run_01")


def add_document_text(session: Session, text: str) -> str:
    """Store a document text version; returns its hash."""
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with write_transaction(session):
        session.execute(
            insert(DocumentText)
            .values(text_hash=text_hash, text=text, char_count=len(text), created_at=utc_now())
            .prefix_with("OR IGNORE")
        )
    return text_hash


def create_document(
    session: Session, title: str = "Example document", *, text: str | None = None, **fields: Any
) -> ChangeResult:
    """Create a document; with ``text`` it gets a stored full text (collector channel)."""
    data: dict[str, Any] = {"title": title, **fields}
    if text is not None:
        data["text_hash"] = add_document_text(session, text)
        return apply_change(session, "document", None, data, COLLECTOR)
    return apply_change(session, "document", None, data, USER)


def create(session: Session, entity_type: str, actor: Actor = USER, **fields: Any) -> ChangeResult:
    """Create any entity with the given fields."""
    return apply_change(session, entity_type, None, fields, actor)


def update(
    session: Session, entity_type: str, entity_id: str, actor: Actor = USER, **fields: Any
) -> ChangeResult:
    """Change fields of an entity."""
    return apply_change(session, entity_type, entity_id, fields, actor)


def listing(session: Session, entity_type: str, **params: str) -> dict[str, Any]:
    """``list_entities`` with keyword parameters (``f_status`` → ``f.status``)."""
    return list_entities(session, entity_type, as_params(params))


def as_params(params: Mapping[str, str]) -> dict[str, str]:
    """Translate ``f_<field>`` keyword names to ``f.<field>``."""
    return {
        (f"f.{key[2:]}" if key.startswith("f_") else key): value for key, value in params.items()
    }


def ids_of(result: Mapping[str, Any]) -> list[str]:
    """The item IDs of a list result, in order."""
    return [item["id"] for item in result["items"]]


@contextmanager
def count_statements(engine: Engine) -> Iterator[list[str]]:
    """Collect the SQL statements executed on ``engine`` inside the block."""
    statements: list[str] = []

    def before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


def open_copy(
    tmp_path_factory: Any, template_db: Path, codebook_dir: Path, seed_dir: Path, name: str
) -> Db:
    """A copy of the migrated template database for a module-scoped catalog."""
    root = tmp_path_factory.mktemp(name)
    shutil.copyfile(template_db, root / "app.db")
    return open_db(root, make_settings(root, codebook_dir, seed_dir))


def assert_consistent(database: Db) -> None:
    """``mdt check`` finds nothing (rows, revisions, FTS and derived rows agree)."""
    with database.session() as session:
        report = run_check(session, database.settings)
    assert report.ok, report.problems


def term_id(session: Session, vocabulary: str, code: str) -> str:
    """The ID of a vocabulary term."""
    with read_transaction(session):
        return str(
            session.execute(
                select(VocabularyTerm.id).where(
                    VocabularyTerm.vocabulary == vocabulary, VocabularyTerm.code == code
                )
            ).scalar_one()
        )
