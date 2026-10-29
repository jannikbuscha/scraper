"""Initial schema: all tables, indexes, the append-only triggers and the FTS5 tables.

Creates every table of docs/DATA_MODEL.md §2.3, §3 and §4. Timestamps are TEXT
(``mdt.db.types.UtcTimestamp`` in the models). The trigger and FTS DDL comes from
``mdt.db.ddl`` (DATA_MODEL §11.1).

Revision ID: 0001
Revises:
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mdt.db.ddl import create_fts_tables, create_revision_triggers, drop_fts_tables

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_state")),
    )
    op.create_table(
        "comment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["comment.id"],
            name=op.f("fk_comment_parent_id_comment"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comment")),
    )
    with op.batch_alter_table("comment", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_comment_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_comment_parent_id"), ["parent_id"], unique=False)
        batch_op.create_index(
            "ix_comment_subject_id_status", ["subject_id", "status"], unique=False
        )

    op.create_table(
        "component",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("name_uk", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("component_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_component")),
    )
    with op.batch_alter_table("component", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_component_deleted_at"), ["deleted_at"], unique=False)

    op.create_table(
        "derived",
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("launch_start", sa.Text(), nullable=True),
        sa.Column("launch_end", sa.Text(), nullable=True),
        sa.Column("launch_value", sa.Text(), nullable=True),
        sa.Column("launch_precision", sa.Text(), nullable=True),
        sa.Column("launch_basis", sa.Text(), nullable=True),
        sa.Column("launch_event_id", sa.Text(), nullable=True),
        sa.Column("existed_by", sa.Text(), nullable=True),
        sa.Column("existed_by_event_id", sa.Text(), nullable=True),
        sa.Column(
            "existed_before_invasion", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("period_reason", sa.Text(), nullable=True),
        sa.Column("war_trajectory", sa.Text(), nullable=False),
        sa.Column("trajectory_reason", sa.Text(), nullable=True),
        sa.Column("trajectory_event_id", sa.Text(), nullable=True),
        sa.Column("portfolio_entry_start", sa.Text(), nullable=True),
        sa.Column("portfolio_entry_end", sa.Text(), nullable=True),
        sa.Column("portfolio_entry_value", sa.Text(), nullable=True),
        sa.Column("portfolio_entry_precision", sa.Text(), nullable=True),
        sa.Column("portfolio_entry_participation_id", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("entity_id", name=op.f("pk_derived")),
    )
    with op.batch_alter_table("derived", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_derived_period"), ["period"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_derived_war_trajectory"), ["war_trajectory"], unique=False
        )

    op.create_table(
        "document_text",
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("text_hash", name=op.f("pk_document_text")),
    )
    op.create_table(
        "event",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("date_start", sa.Text(), nullable=True),
        sa.Column("date_end", sa.Text(), nullable=True),
        sa.Column("date_precision", sa.Text(), nullable=True),
        sa.Column("date_basis", sa.Text(), nullable=True),
        sa.Column("date_text", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_uk", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event")),
    )
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_event_date_start"), ["date_start"], unique=False)
        batch_op.create_index(batch_op.f("ix_event_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_event_subject_id"), ["subject_id"], unique=False)

    op.create_table(
        "indicator",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("as_of_start", sa.Text(), nullable=True),
        sa.Column("as_of_end", sa.Text(), nullable=True),
        sa.Column("as_of_precision", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indicator")),
    )
    with op.batch_alter_table("indicator", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_indicator_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_indicator_subject_id"), ["subject_id"], unique=False)

    op.create_table(
        "organization",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("seed_key", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("name_uk", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("org_type", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization")),
        sa.UniqueConstraint("seed_key", name=op.f("uq_organization_seed_key")),
        sa.UniqueConstraint("slug", name=op.f("uq_organization_slug")),
    )
    with op.batch_alter_table("organization", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_organization_deleted_at"), ["deleted_at"], unique=False
        )

    op.create_table(
        "project",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("seed_key", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("name_uk", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_uk", sa.Text(), nullable=True),
        sa.Column("official_urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("ministry_urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("in_paper_scope", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("paper_cluster", sa.Text(), nullable=True),
        sa.Column("unit_type", sa.Text(), nullable=True),
        sa.Column("ministry_categories", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("primary_objectives", sa.Text(), nullable=True),
        sa.Column("policy_domains", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("beneficiaries", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("development_mode", sa.Text(), nullable=True),
        sa.Column("development_rationale", sa.Text(), nullable=True),
        sa.Column("wartime_relevance", sa.Text(), nullable=True),
        sa.Column("wartime_rationale", sa.Text(), nullable=True),
        sa.Column("d1_need", sa.Text(), nullable=True),
        sa.Column("d1_affected_groups", sa.Text(), nullable=True),
        sa.Column("d1_priority_link", sa.Text(), nullable=True),
        sa.Column("d2_summary", sa.Text(), nullable=True),
        sa.Column("d3_summary", sa.Text(), nullable=True),
        sa.Column("d4_summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
        sa.UniqueConstraint("seed_key", name=op.f("uq_project_seed_key")),
        sa.UniqueConstraint("slug", name=op.f("uq_project_slug")),
    )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_project_deleted_at"), ["deleted_at"], unique=False)

    op.create_table(
        "relation",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("from_id", sa.Text(), nullable=False),
        sa.Column("to_id", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relation")),
    )
    with op.batch_alter_table("relation", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_relation_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_relation_from_id"), ["from_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_relation_to_id"), ["to_id"], unique=False)

    op.create_table(
        "revision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("proposal_id", sa.Text(), nullable=True),
        sa.Column("restored_from", sa.Integer(), nullable=True),
        sa.Column("restored_from_version", sa.Integer(), nullable=True),
        sa.Column("batch_id", sa.Text(), nullable=True),
        sa.Column("schema_revision", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revision")),
        sa.UniqueConstraint("entity_id", "version", name=op.f("uq_revision_entity_id_version")),
        sqlite_autoincrement=True,
    )
    with op.batch_alter_table("revision", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_revision_at"), ["at"], unique=False)
        batch_op.create_index(batch_op.f("ix_revision_author"), ["author"], unique=False)
        batch_op.create_index(batch_op.f("ix_revision_batch_id"), ["batch_id"], unique=False)
        batch_op.create_index("ix_revision_entity_type_id", ["entity_type", "id"], unique=False)

    op.create_table(
        "saved_view",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_view")),
    )
    with op.batch_alter_table("saved_view", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_saved_view_deleted_at"), ["deleted_at"], unique=False)

    op.create_table(
        "search_key",
        sa.Column("rowid", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("rowid", name=op.f("pk_search_key")),
        sa.UniqueConstraint("entity_id", name=op.f("uq_search_key_entity_id")),
    )
    op.create_table(
        "vocabulary",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("multi", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("fixed_codes", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_vocabulary")),
    )
    op.create_table(
        "document",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("publisher_org_id", sa.Text(), nullable=True),
        sa.Column("doc_type", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("published_start", sa.Text(), nullable=True),
        sa.Column("published_end", sa.Text(), nullable=True),
        sa.Column("published_precision", sa.Text(), nullable=True),
        sa.Column("published_basis", sa.Text(), nullable=True),
        sa.Column("published_text", sa.Text(), nullable=True),
        sa.Column("published_at_utc", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=True),
        sa.Column("text_hash", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=True),
        sa.Column("archive_urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("license", sa.Text(), nullable=True),
        sa.Column(
            "screening_status", sa.Text(), server_default=sa.text("'unscreened'"), nullable=False
        ),
        sa.Column("screening_reason", sa.Text(), nullable=True),
        sa.Column("screening_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["publisher_org_id"],
            ["organization.id"],
            name=op.f("fk_document_publisher_org_id_organization"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
    )
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_document_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_document_published_start"), ["published_start"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_document_retrieved_at"), ["retrieved_at"], unique=False
        )
        batch_op.create_index(
            "uq_document_canonical_url_live",
            ["canonical_url"],
            unique=True,
            sqlite_where=sa.text("deleted_at IS NULL AND canonical_url IS NOT NULL"),
        )

    op.create_table(
        "participation",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("start_start", sa.Text(), nullable=True),
        sa.Column("start_end", sa.Text(), nullable=True),
        sa.Column("start_precision", sa.Text(), nullable=True),
        sa.Column("end_start", sa.Text(), nullable=True),
        sa.Column("end_end", sa.Text(), nullable=True),
        sa.Column("end_precision", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name=op.f("fk_participation_organization_id_organization"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participation")),
    )
    with op.batch_alter_table("participation", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_participation_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_participation_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_participation_subject_id"), ["subject_id"], unique=False
        )

    op.create_table(
        "service",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("parent_service_id", sa.Text(), nullable=True),
        sa.Column("name_en", sa.Text(), nullable=True),
        sa.Column("name_uk", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("description_uk", sa.Text(), nullable=True),
        sa.Column("urls", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=True),
        sa.Column("channels", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("source_categories", sa.JSON(), nullable=True),
        sa.Column("source_audiences", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("policy_domains", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("beneficiaries", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("development_mode", sa.Text(), nullable=True),
        sa.Column("development_rationale", sa.Text(), nullable=True),
        sa.Column("wartime_relevance", sa.Text(), nullable=True),
        sa.Column("wartime_rationale", sa.Text(), nullable=True),
        sa.Column("d1_need", sa.Text(), nullable=True),
        sa.Column("d1_affected_groups", sa.Text(), nullable=True),
        sa.Column("d1_priority_link", sa.Text(), nullable=True),
        sa.Column("d2_summary", sa.Text(), nullable=True),
        sa.Column("d3_summary", sa.Text(), nullable=True),
        sa.Column("d4_summary", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_service_id"],
            ["service.id"],
            name=op.f("fk_service_parent_service_id_service"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_service_project_id_project"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service")),
    )
    with op.batch_alter_table("service", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_service_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_service_parent_service_id"), ["parent_service_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_service_project_id"), ["project_id"], unique=False)

    op.create_table(
        "vocabulary_term",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("vocabulary", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label_en", sa.Text(), nullable=False),
        sa.Column("label_uk", sa.Text(), nullable=True),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("include_note", sa.Text(), nullable=True),
        sa.Column("exclude_note", sa.Text(), nullable=True),
        sa.Column("examples", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("replaced_by", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["vocabulary"],
            ["vocabulary.name"],
            name=op.f("fk_vocabulary_term_vocabulary_vocabulary"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vocabulary_term")),
        sa.UniqueConstraint("vocabulary", "code", name=op.f("uq_vocabulary_term_vocabulary_code")),
    )
    with op.batch_alter_table("vocabulary_term", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_vocabulary_term_deleted_at"), ["deleted_at"], unique=False
        )

    op.create_table(
        "document_link",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("matched_aliases", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("match_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_document_link_document_id_document"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_link")),
        sa.UniqueConstraint(
            "document_id", "subject_id", name=op.f("uq_document_link_document_id_subject_id")
        ),
    )
    with op.batch_alter_table("document_link", schema=None) as batch_op:
        batch_op.create_index(
            "ix_document_link_subject_id_state_document_id",
            ["subject_id", "state", "document_id"],
            unique=False,
        )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("archive_url", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.Text(), nullable=True),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=True),
        sa.Column("text_hash", sa.Text(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("value_snapshot", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
        sa.Column("deleted_by", sa.Text(), nullable=True),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "verification_status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("field_meta", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_evidence_document_id_document"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_evidence_deleted_at"), ["deleted_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_evidence_subject_id"), ["subject_id"], unique=False)

    connection = op.get_bind()
    create_revision_triggers(connection)
    create_fts_tables(connection)


def downgrade() -> None:
    drop_fts_tables(op.get_bind())
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_subject_id"))
        batch_op.drop_index(batch_op.f("ix_evidence_deleted_at"))

    op.drop_table("evidence")
    with op.batch_alter_table("document_link", schema=None) as batch_op:
        batch_op.drop_index("ix_document_link_subject_id_state_document_id")

    op.drop_table("document_link")
    with op.batch_alter_table("vocabulary_term", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vocabulary_term_deleted_at"))

    op.drop_table("vocabulary_term")
    with op.batch_alter_table("service", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_service_project_id"))
        batch_op.drop_index(batch_op.f("ix_service_parent_service_id"))
        batch_op.drop_index(batch_op.f("ix_service_deleted_at"))

    op.drop_table("service")
    with op.batch_alter_table("participation", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_participation_subject_id"))
        batch_op.drop_index(batch_op.f("ix_participation_organization_id"))
        batch_op.drop_index(batch_op.f("ix_participation_deleted_at"))

    op.drop_table("participation")
    with op.batch_alter_table("document", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_document_canonical_url_live",
            sqlite_where=sa.text("deleted_at IS NULL AND canonical_url IS NOT NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_document_retrieved_at"))
        batch_op.drop_index(batch_op.f("ix_document_published_start"))
        batch_op.drop_index(batch_op.f("ix_document_deleted_at"))

    op.drop_table("document")
    op.drop_table("vocabulary")
    op.drop_table("search_key")
    with op.batch_alter_table("saved_view", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_saved_view_deleted_at"))

    op.drop_table("saved_view")
    with op.batch_alter_table("revision", schema=None) as batch_op:
        batch_op.drop_index("ix_revision_entity_type_id")
        batch_op.drop_index(batch_op.f("ix_revision_batch_id"))
        batch_op.drop_index(batch_op.f("ix_revision_author"))
        batch_op.drop_index(batch_op.f("ix_revision_at"))

    op.drop_table("revision")
    with op.batch_alter_table("relation", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_relation_to_id"))
        batch_op.drop_index(batch_op.f("ix_relation_from_id"))
        batch_op.drop_index(batch_op.f("ix_relation_deleted_at"))

    op.drop_table("relation")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_project_deleted_at"))

    op.drop_table("project")
    with op.batch_alter_table("organization", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_organization_deleted_at"))

    op.drop_table("organization")
    with op.batch_alter_table("indicator", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_indicator_subject_id"))
        batch_op.drop_index(batch_op.f("ix_indicator_deleted_at"))

    op.drop_table("indicator")
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_event_subject_id"))
        batch_op.drop_index(batch_op.f("ix_event_deleted_at"))
        batch_op.drop_index(batch_op.f("ix_event_date_start"))

    op.drop_table("event")
    op.drop_table("document_text")
    with op.batch_alter_table("derived", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_derived_war_trajectory"))
        batch_op.drop_index(batch_op.f("ix_derived_period"))

    op.drop_table("derived")
    with op.batch_alter_table("component", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_component_deleted_at"))

    op.drop_table("component")
    with op.batch_alter_table("comment", schema=None) as batch_op:
        batch_op.drop_index("ix_comment_subject_id_status")
        batch_op.drop_index(batch_op.f("ix_comment_parent_id"))
        batch_op.drop_index(batch_op.f("ix_comment_deleted_at"))

    op.drop_table("comment")
    op.drop_table("app_state")
