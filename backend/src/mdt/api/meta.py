"""Meta, lookup and statistics endpoints (docs/API.md §3.1)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from mdt import __version__
from mdt.api.deps import SessionDep, SettingsDep
from mdt.config import Settings
from mdt.db.models import Vocabulary
from mdt.db.session import read_transaction
from mdt.domain import derived
from mdt.domain.listquery import MAX_PAGE_SIZE
from mdt.domain.lookup import lookup as lookup_entities
from mdt.domain.normalize import MAX_NOTE_CHARS
from mdt.domain.query import entity_stats, vocabulary_listing
from mdt.domain.registry import GROUPS, meta_entity_types
from mdt.domain.revisions import MAX_BULK_ITEMS
from mdt.domain.vocab import load_parameters


def health(session: SessionDep) -> dict[str, Any]:
    """``GET /api/health``: liveness plus the schema revision read from the database."""
    with read_transaction(session):
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {"status": "ok", "version": __version__, "schema_revision": revision}


def meta_payload(session: Session, settings: Settings) -> dict[str, Any]:
    """The ``GET /api/meta`` document: registry, groups, limits, vocabulary metadata,
    cut-off dates and the focal organisation."""
    parameters = load_parameters(settings.codebook_path)
    with read_transaction(session):
        focal_org_id = derived.focal_org_id(session, settings)
        vocabularies = {
            vocabulary.name: {
                "label": vocabulary.label,
                "multi": bool(vocabulary.multi),
                "fixed_codes": bool(vocabulary.fixed_codes),
            }
            for vocabulary in session.scalars(select(Vocabulary).order_by(Vocabulary.name))
        }
    return {
        "app_version": __version__,
        "focal_org_id": focal_org_id,
        "parameters": parameters.as_api(),
        "limits": {
            "max_comment_chars": settings.max_comment_chars,
            "max_note_chars": MAX_NOTE_CHARS,
            "max_page_size": MAX_PAGE_SIZE,
            "max_bulk_items": MAX_BULK_ITEMS,
        },
        "groups": [dict(group) for group in GROUPS],
        "vocabularies": vocabularies,
        "entity_types": meta_entity_types(parameters.period),
    }


def get_meta(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    """``GET /api/meta``."""
    return meta_payload(session, settings)


def get_vocab(session: SessionDep) -> dict[str, Any]:
    """``GET /api/vocab``: vocabularies with their terms, usage counts and open comments."""
    return vocabulary_listing(session)


def get_stats(session: SessionDep) -> dict[str, Any]:
    """``GET /api/stats``: counts per entity type and open comment threads."""
    return entity_stats(session)


def get_lookup(request: Request, session: SessionDep) -> dict[str, Any]:
    """``GET /api/lookup``: labels by prefix/full-text search or for a list of IDs."""
    return lookup_entities(session, request.query_params)


def register(app: FastAPI) -> None:
    """Add the meta routes."""
    app.add_api_route("/api/health", health, methods=["GET"])
    app.add_api_route("/api/meta", get_meta, methods=["GET"])
    app.add_api_route("/api/vocab", get_vocab, methods=["GET"])
    app.add_api_route("/api/stats", get_stats, methods=["GET"])
    app.add_api_route("/api/lookup", get_lookup, methods=["GET"])
