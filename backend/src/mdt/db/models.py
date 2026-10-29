"""SQLAlchemy models for every table of docs/DATA_MODEL.md §2.3, §3 and §4.

The FTS5 virtual tables (``fts_entity``, ``fts_document``) and the append-only triggers
on ``revision`` are not models; their DDL lives in :mod:`mdt.db.ddl`.

The write path (:mod:`mdt.domain.revisions`) uses the ``__table__`` objects through
SQLAlchemy Core, so every row update is an explicit compare-and-swap on ``version``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mdt.db.types import JsonValue, NullableJson, UtcTimestamp

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

EMPTY_LIST = text("'[]'")
EMPTY_OBJECT = text("'{}'")


class Base(DeclarativeBase):
    """Declarative base with a naming convention (stable names for batch migrations)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _restrict(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT")


class CuratedMixin:
    """Common columns of every curated entity (DATA_MODEL §2.3)."""

    id: Mapped[str] = mapped_column(Text, primary_key=True, sort_order=-100)
    version: Mapped[int] = mapped_column(Integer, nullable=False, sort_order=100)
    created_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False, sort_order=101)
    created_by: Mapped[str] = mapped_column(Text, nullable=False, sort_order=102)
    updated_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False, sort_order=103)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False, sort_order=104)
    deleted_at: Mapped[str | None] = mapped_column(UtcTimestamp, index=True, sort_order=105)
    deleted_by: Mapped[str | None] = mapped_column(Text, sort_order=106)
    merged_into: Mapped[str | None] = mapped_column(Text, sort_order=107)
    verification_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unverified'"), sort_order=108
    )
    notes: Mapped[str | None] = mapped_column(Text, sort_order=109)
    field_meta: Mapped[dict[str, Any]] = mapped_column(
        JsonValue, nullable=False, server_default=EMPTY_OBJECT, sort_order=110
    )


def _list_column() -> Mapped[list[Any]]:
    return mapped_column(JsonValue, nullable=False, server_default=EMPTY_LIST)


# --------------------------------------------------------------------------------------
# Curated entities (DATA_MODEL §3)
# --------------------------------------------------------------------------------------


class Project(CuratedMixin, Base):
    """A project of the ministry's portfolio (DATA_MODEL §3.1)."""

    __tablename__ = "project"

    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    seed_key: Mapped[str | None] = mapped_column(Text, unique=True)
    name_en: Mapped[str | None] = mapped_column(Text)
    name_uk: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[Any]] = _list_column()
    description_en: Mapped[str | None] = mapped_column(Text)
    description_uk: Mapped[str | None] = mapped_column(Text)
    official_urls: Mapped[list[Any]] = _list_column()
    ministry_urls: Mapped[list[Any]] = _list_column()
    in_paper_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    scope_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    paper_cluster: Mapped[str | None] = mapped_column(Text)
    unit_type: Mapped[str | None] = mapped_column(Text)
    ministry_categories: Mapped[list[Any]] = _list_column()
    primary_objectives: Mapped[str | None] = mapped_column(Text)
    policy_domains: Mapped[list[Any]] = _list_column()
    beneficiaries: Mapped[list[Any]] = _list_column()
    development_mode: Mapped[str | None] = mapped_column(Text)
    development_rationale: Mapped[str | None] = mapped_column(Text)
    wartime_relevance: Mapped[str | None] = mapped_column(Text)
    wartime_rationale: Mapped[str | None] = mapped_column(Text)
    d1_need: Mapped[str | None] = mapped_column(Text)
    d1_affected_groups: Mapped[str | None] = mapped_column(Text)
    d1_priority_link: Mapped[str | None] = mapped_column(Text)
    d2_summary: Mapped[str | None] = mapped_column(Text)
    d3_summary: Mapped[str | None] = mapped_column(Text)
    d4_summary: Mapped[str | None] = mapped_column(Text)


class Service(CuratedMixin, Base):
    """A service or sub-service of a project (DATA_MODEL §3.2)."""

    __tablename__ = "service"

    project_id: Mapped[str] = mapped_column(
        Text, _restrict("project.id"), nullable=False, index=True
    )
    parent_service_id: Mapped[str | None] = mapped_column(Text, _restrict("service.id"), index=True)
    name_en: Mapped[str | None] = mapped_column(Text)
    name_uk: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[Any]] = _list_column()
    description_en: Mapped[str | None] = mapped_column(Text)
    description_uk: Mapped[str | None] = mapped_column(Text)
    urls: Mapped[list[Any]] = _list_column()
    status: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)
    channels: Mapped[list[Any]] = _list_column()
    source_categories: Mapped[Any] = mapped_column(NullableJson, nullable=True)
    source_audiences: Mapped[list[Any]] = _list_column()
    policy_domains: Mapped[list[Any]] = _list_column()
    beneficiaries: Mapped[list[Any]] = _list_column()
    development_mode: Mapped[str | None] = mapped_column(Text)
    development_rationale: Mapped[str | None] = mapped_column(Text)
    wartime_relevance: Mapped[str | None] = mapped_column(Text)
    wartime_rationale: Mapped[str | None] = mapped_column(Text)
    d1_need: Mapped[str | None] = mapped_column(Text)
    d1_affected_groups: Mapped[str | None] = mapped_column(Text)
    d1_priority_link: Mapped[str | None] = mapped_column(Text)
    d2_summary: Mapped[str | None] = mapped_column(Text)
    d3_summary: Mapped[str | None] = mapped_column(Text)
    d4_summary: Mapped[str | None] = mapped_column(Text)


class Event(CuratedMixin, Base):
    """An introduction or modification event with a partial date (DATA_MODEL §3.3)."""

    __tablename__ = "event"

    subject_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    date_start: Mapped[str | None] = mapped_column(Text, index=True)
    date_end: Mapped[str | None] = mapped_column(Text)
    date_precision: Mapped[str | None] = mapped_column(Text)
    date_basis: Mapped[str | None] = mapped_column(Text)
    date_text: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_uk: Mapped[str | None] = mapped_column(Text)


class Document(CuratedMixin, Base):
    """A source document; its links live in ``document_link`` (DATA_MODEL §3.4)."""

    __tablename__ = "document"
    __table_args__ = (
        Index(
            "uq_document_canonical_url_live",
            "canonical_url",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND canonical_url IS NOT NULL"),
        ),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    publisher_org_id: Mapped[str | None] = mapped_column(Text, _restrict("organization.id"))
    doc_type: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    published_start: Mapped[str | None] = mapped_column(Text, index=True)
    published_end: Mapped[str | None] = mapped_column(Text)
    published_precision: Mapped[str | None] = mapped_column(Text)
    published_basis: Mapped[str | None] = mapped_column(Text)
    published_text: Mapped[str | None] = mapped_column(Text)
    published_at_utc: Mapped[str | None] = mapped_column(UtcTimestamp)
    retrieved_at: Mapped[str | None] = mapped_column(UtcTimestamp, index=True)
    source_id: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    raw_snapshot_id: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(Text)
    archive_urls: Mapped[list[Any]] = _list_column()
    license: Mapped[str | None] = mapped_column(Text)
    screening_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unscreened'")
    )
    screening_reason: Mapped[str | None] = mapped_column(Text)
    screening_note: Mapped[str | None] = mapped_column(Text)


class Organization(CuratedMixin, Base):
    """An organisation, including the seeded focal organisation (DATA_MODEL §3.5)."""

    __tablename__ = "organization"

    slug: Mapped[str | None] = mapped_column(Text, unique=True)
    seed_key: Mapped[str | None] = mapped_column(Text, unique=True)
    name_en: Mapped[str | None] = mapped_column(Text)
    name_uk: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[Any]] = _list_column()
    org_type: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    urls: Mapped[list[Any]] = _list_column()
    description: Mapped[str | None] = mapped_column(Text)


class Participation(CuratedMixin, Base):
    """An organisation's role in a project, service or component (D3)."""

    __tablename__ = "participation"

    organization_id: Mapped[str] = mapped_column(
        Text, _restrict("organization.id"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    start_start: Mapped[str | None] = mapped_column(Text)
    start_end: Mapped[str | None] = mapped_column(Text)
    start_precision: Mapped[str | None] = mapped_column(Text)
    end_start: Mapped[str | None] = mapped_column(Text)
    end_end: Mapped[str | None] = mapped_column(Text)
    end_precision: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Component(CuratedMixin, Base):
    """A platform or infrastructure component that is not a portfolio project."""

    __tablename__ = "component"

    name_en: Mapped[str | None] = mapped_column(Text)
    name_uk: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[Any]] = _list_column()
    component_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    urls: Mapped[list[Any]] = _list_column()


class Relation(CuratedMixin, Base):
    """A relation between projects, services and components (D2, D4)."""

    __tablename__ = "relation"

    from_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    to_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Indicator(CuratedMixin, Base):
    """A reported figure about a subject."""

    __tablename__ = "indicator"

    subject_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    as_of_start: Mapped[str | None] = mapped_column(Text)
    as_of_end: Mapped[str | None] = mapped_column(Text)
    as_of_precision: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Evidence(CuratedMixin, Base):
    """A citation that supports a record, one of its fields or a dimension."""

    __tablename__ = "evidence"

    subject_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str | None] = mapped_column(Text, _restrict("document.id"))
    url: Mapped[str | None] = mapped_column(Text)
    archive_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[str | None] = mapped_column(UtcTimestamp)
    raw_snapshot_id: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    value_snapshot: Mapped[Any] = mapped_column(NullableJson, nullable=True)


class VocabularyTerm(CuratedMixin, Base):
    """A term of a controlled vocabulary; never deleted, only deactivated."""

    __tablename__ = "vocabulary_term"
    __table_args__ = (UniqueConstraint("vocabulary", "code"),)

    vocabulary: Mapped[str] = mapped_column(Text, _restrict("vocabulary.name"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    label_uk: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[str | None] = mapped_column(Text)
    include_note: Mapped[str | None] = mapped_column(Text)
    exclude_note: Mapped[str | None] = mapped_column(Text)
    examples: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    replaced_by: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[Any] = mapped_column(NullableJson, nullable=True)


class SavedView(CuratedMixin, Base):
    """A saved table view (canonical query string), visible to everyone."""

    __tablename__ = "saved_view"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------------------
# System tables (DATA_MODEL §4)
# --------------------------------------------------------------------------------------


class Vocabulary(Base):
    """Vocabulary metadata loaded from ``codebook/*.yaml`` (not revisioned)."""

    __tablename__ = "vocabulary"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    multi: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    fixed_codes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    source_file: Mapped[str | None] = mapped_column(Text)


class Revision(Base):
    """One append-only revision with a full snapshot and a diff (DATA_MODEL §4, §6.3)."""

    __tablename__ = "revision"
    __table_args__ = (
        UniqueConstraint("entity_id", "version"),
        Index("ix_revision_entity_type_id", "entity_type", "id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False, index=True)
    author: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[str | None] = mapped_column(Text)
    restored_from: Mapped[int | None] = mapped_column(Integer)
    restored_from_version: Mapped[int | None] = mapped_column(Integer)
    batch_id: Mapped[str | None] = mapped_column(Text, index=True)
    schema_revision: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JsonValue, nullable=False)
    diff: Mapped[dict[str, Any]] = mapped_column(JsonValue, nullable=False)


class Comment(Base):
    """A comment or reply on any curated record (DATA_MODEL §6.6)."""

    __tablename__ = "comment"
    __table_args__ = (Index("ix_comment_subject_id_status", "subject_id", "status"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(Text, _restrict("comment.id"), index=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[str | None] = mapped_column(UtcTimestamp)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    deleted_at: Mapped[str | None] = mapped_column(UtcTimestamp, index=True)
    deleted_by: Mapped[str | None] = mapped_column(Text)


class DocumentText(Base):
    """An immutable, content-addressed text version of a document."""

    __tablename__ = "document_text"

    text_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False)


class DocumentLink(Base):
    """A link from a document to a project or service (part of its snapshot)."""

    __tablename__ = "document_link"
    __table_args__ = (
        UniqueConstraint("document_id", "subject_id"),
        Index(
            "ix_document_link_subject_id_state_document_id", "subject_id", "state", "document_id"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(Text, _restrict("document.id"), nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    matched_aliases: Mapped[list[Any]] = _list_column()
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    snippet: Mapped[str | None] = mapped_column(Text)


class Derived(Base):
    """Derived values of a project or service (DATA_MODEL §8); one row per entity."""

    __tablename__ = "derived"

    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    launch_start: Mapped[str | None] = mapped_column(Text)
    launch_end: Mapped[str | None] = mapped_column(Text)
    launch_value: Mapped[str | None] = mapped_column(Text)
    launch_precision: Mapped[str | None] = mapped_column(Text)
    launch_basis: Mapped[str | None] = mapped_column(Text)
    launch_event_id: Mapped[str | None] = mapped_column(Text)
    existed_by: Mapped[str | None] = mapped_column(Text)
    existed_by_event_id: Mapped[str | None] = mapped_column(Text)
    existed_before_invasion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    period: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    period_reason: Mapped[str | None] = mapped_column(Text)
    war_trajectory: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    trajectory_reason: Mapped[str | None] = mapped_column(Text)
    trajectory_event_id: Mapped[str | None] = mapped_column(Text)
    portfolio_entry_start: Mapped[str | None] = mapped_column(Text)
    portfolio_entry_end: Mapped[str | None] = mapped_column(Text)
    portfolio_entry_value: Mapped[str | None] = mapped_column(Text)
    portfolio_entry_precision: Mapped[str | None] = mapped_column(Text)
    portfolio_entry_participation_id: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[str] = mapped_column(UtcTimestamp, nullable=False)


class SearchKey(Base):
    """Stable integer keys for the FTS tables (DATA_MODEL §10)."""

    __tablename__ = "search_key"

    rowid: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)


class AppState(Base):
    """Key-value state of the application, e.g. the derived-inputs hash."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


#: Model class per curated entity type, in registry order.
CURATED_MODELS: dict[str, type[Base]] = {
    "project": Project,
    "service": Service,
    "event": Event,
    "document": Document,
    "organization": Organization,
    "participation": Participation,
    "component": Component,
    "relation": Relation,
    "indicator": Indicator,
    "evidence": Evidence,
    "vocabulary_term": VocabularyTerm,
    "saved_view": SavedView,
}

#: Model class per revisioned entity type (curated entities plus comments).
ENTITY_MODELS: dict[str, type[Base]] = {**CURATED_MODELS, "comment": Comment}
