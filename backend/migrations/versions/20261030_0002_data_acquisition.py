"""Data acquisition (Phase 2): the system tables of docs/DATA_MODEL.md §14.

Creates ``collector_run``, ``raw_snapshot`` (with its append-only triggers from
``mdt.db.ddl``), ``fetch_log``, ``run_message``, ``source_observation``, ``proposal``,
``merge_log`` and ``import_run`` with their indexes; adds the nullable column
``document.source_record_at`` with a plain ``ALTER TABLE … ADD COLUMN`` (outside batch
mode, so ``document`` and its partial unique index are not recreated) and the index
``document(source_id, external_id)``. It does not alter ``revision``: ``run_id`` and
``proposal_id`` exist since 0001 (DATA_MODEL §11 item 7). The downgrade drops what the
upgrade created.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mdt.db.ddl import create_raw_snapshot_triggers, drop_raw_snapshot_triggers

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _restrict(column: str, table: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}"), ondelete="RESTRICT"
    )


def upgrade() -> None:
    op.create_table(
        "collector_run",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("collector", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("heartbeat_at", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.Text(), nullable=True),
        sa.Column("complete_listing", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("stats", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collector_run")),
    )
    op.create_index(op.f("ix_collector_run_status"), "collector_run", ["status"], unique=False)
    op.create_index(
        "ix_collector_run_collector_started_at",
        "collector_run",
        ["collector", "started_at"],
        unique=False,
    )
    op.create_index(
        "uq_collector_run_running",
        "collector_run",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "raw_snapshot",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("via", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("redirects", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.Text(), nullable=False),
        sa.Column("headers", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        _restrict("run_id", "raw_snapshot", "collector_run"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_snapshot")),
    )
    op.create_index(op.f("ix_raw_snapshot_run_id"), "raw_snapshot", ["run_id"], unique=False)
    op.create_index(op.f("ix_raw_snapshot_url"), "raw_snapshot", ["url"], unique=False)
    op.create_index(op.f("ix_raw_snapshot_sha256"), "raw_snapshot", ["sha256"], unique=False)
    op.create_index(
        "ix_raw_snapshot_source_id_fetched_at",
        "raw_snapshot",
        ["source_id", "fetched_at"],
        unique=False,
    )

    op.create_table(
        "fetch_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("at", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=True),
        sa.Column("retry_after_s", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _restrict("run_id", "fetch_log", "collector_run"),
        _restrict("raw_snapshot_id", "fetch_log", "raw_snapshot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fetch_log")),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_fetch_log_run_id_id", "fetch_log", ["run_id", "id"], unique=False)
    op.create_index("ix_fetch_log_host_at", "fetch_log", ["host", "at"], unique=False)
    op.create_index(op.f("ix_fetch_log_url"), "fetch_log", ["url"], unique=False)

    op.create_table(
        "run_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=True),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        _restrict("run_id", "run_message", "collector_run"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_message")),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_run_message_run_id_level_id", "run_message", ["run_id", "level", "id"], unique=False
    )

    op.create_table(
        "source_observation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collector", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("bound_by", sa.Text(), nullable=True),
        sa.Column("bound_at", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.Text(), nullable=False),
        sa.Column("first_seen_run", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.Column("last_seen_run", sa.Text(), nullable=False),
        sa.Column("present", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("missing_since_at", sa.Text(), nullable=True),
        sa.Column("missing_since_run", sa.Text(), nullable=True),
        sa.Column("missing_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_snapshot_id", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        _restrict("last_snapshot_id", "source_observation", "raw_snapshot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_observation")),
        sa.UniqueConstraint("collector", "key", name=op.f("uq_source_observation_collector_key")),
        sqlite_autoincrement=True,
    )
    op.create_index(
        op.f("ix_source_observation_subject_id"),
        "source_observation",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        "ix_source_observation_collector_present",
        "source_observation",
        ["collector", "present"],
        unique=False,
    )
    op.create_index(
        "ix_source_observation_collector_external_id",
        "source_observation",
        ["collector", "external_id"],
        unique=False,
    )

    op.create_table(
        "proposal",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("related_id", sa.Text(), nullable=True),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("current_value", sa.JSON(), nullable=True),
        sa.Column("proposed_value", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("collector", sa.Text(), nullable=False),
        sa.Column("first_run_id", sa.Text(), nullable=False),
        sa.Column("last_run_id", sa.Text(), nullable=False),
        sa.Column("raw_snapshot_id", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("locator", sa.Text(), nullable=True),
        sa.Column("observation_id", sa.Integer(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column("seen_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("result_id", sa.Text(), nullable=True),
        _restrict("first_run_id", "proposal", "collector_run"),
        _restrict("last_run_id", "proposal", "collector_run"),
        _restrict("raw_snapshot_id", "proposal", "raw_snapshot"),
        _restrict("observation_id", "proposal", "source_observation"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal")),
    )
    op.create_index(
        "uq_proposal_dedup_key_open",
        "proposal",
        ["dedup_key"],
        unique=True,
        sqlite_where=sa.text("state = 'open'"),
    )
    op.create_index("ix_proposal_state_kind", "proposal", ["state", "kind"], unique=False)
    op.create_index(
        "ix_proposal_subject_id_state", "proposal", ["subject_id", "state"], unique=False
    )
    op.create_index(
        "ix_proposal_related_id_state", "proposal", ["related_id", "state"], unique=False
    )
    op.create_index("ix_proposal_collector_state", "proposal", ["collector", "state"], unique=False)
    op.create_index(op.f("ix_proposal_last_run_id"), "proposal", ["last_run_id"], unique=False)

    op.create_table(
        "merge_log",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("survivor_id", sa.Text(), nullable=False),
        sa.Column("merged_id", sa.Text(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.Column("batch_id", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("field_choices", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("changes", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("unmerged_at", sa.Text(), nullable=True),
        sa.Column("unmerge_batch_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merge_log")),
    )
    op.create_index(op.f("ix_merge_log_survivor_id"), "merge_log", ["survivor_id"], unique=False)
    op.create_index(op.f("ix_merge_log_merged_id"), "merge_log", ["merged_id"], unique=False)

    op.create_table(
        "import_run",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("upload_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("file_label", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("sheet", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("key_field", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        _restrict("upload_id", "import_run", "raw_snapshot"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_run")),
    )

    # Plain ALTER TABLE (no batch mode): document and its partial index stay as they are.
    op.add_column("document", sa.Column("source_record_at", sa.Text(), nullable=True))
    op.create_index(
        "ix_document_source_id_external_id",
        "document",
        ["source_id", "external_id"],
        unique=False,
    )

    create_raw_snapshot_triggers(op.get_bind())


def downgrade() -> None:
    connection = op.get_bind()
    drop_raw_snapshot_triggers(connection)
    op.drop_index("ix_document_source_id_external_id", table_name="document")
    # SQLite >= 3.35 drops an unindexed column in place (the startup check requires 3.40).
    op.execute("ALTER TABLE document DROP COLUMN source_record_at")
    op.drop_table("import_run")
    op.drop_index(op.f("ix_merge_log_merged_id"), table_name="merge_log")
    op.drop_index(op.f("ix_merge_log_survivor_id"), table_name="merge_log")
    op.drop_table("merge_log")
    for name in (
        op.f("ix_proposal_last_run_id"),
        "ix_proposal_collector_state",
        "ix_proposal_related_id_state",
        "ix_proposal_subject_id_state",
        "ix_proposal_state_kind",
        "uq_proposal_dedup_key_open",
    ):
        op.drop_index(name, table_name="proposal")
    op.drop_table("proposal")
    for name in (
        "ix_source_observation_collector_external_id",
        "ix_source_observation_collector_present",
        op.f("ix_source_observation_subject_id"),
    ):
        op.drop_index(name, table_name="source_observation")
    op.drop_table("source_observation")
    op.drop_index("ix_run_message_run_id_level_id", table_name="run_message")
    op.drop_table("run_message")
    for name in (op.f("ix_fetch_log_url"), "ix_fetch_log_host_at", "ix_fetch_log_run_id_id"):
        op.drop_index(name, table_name="fetch_log")
    op.drop_table("fetch_log")
    for name in (
        "ix_raw_snapshot_source_id_fetched_at",
        op.f("ix_raw_snapshot_sha256"),
        op.f("ix_raw_snapshot_url"),
        op.f("ix_raw_snapshot_run_id"),
    ):
        op.drop_index(name, table_name="raw_snapshot")
    op.drop_table("raw_snapshot")
    for name in (
        "uq_collector_run_running",
        "ix_collector_run_collector_started_at",
        op.f("ix_collector_run_status"),
    ):
        op.drop_index(name, table_name="collector_run")
    op.drop_table("collector_run")
