"""drop issue_work_packs (Phase 4BD.6)

Revision ID: 293_drop_issue_work_packs
Revises: 292_project_intake_config
Create Date: 2026-05-02

Drops the bespoke ``issue_work_packs`` table and clears any stale
``WorkspaceAttentionItem`` rows whose ``target_kind`` was ``issue_intake``.

Substrate now lives in repo-resident markdown artifacts written by the
``propose_run_packs`` tool (4BD.4). Project coding-run launches read
``source_artifact`` from the run config instead of joining to a Run Pack row
(4BD.5).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "293_drop_issue_work_packs"
down_revision = "292_project_intake_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defensive cleanup: the CheckConstraint on workspace_attention_items
    # never permitted target_kind == 'issue_intake', but historical seed
    # data or out-of-band inserts could exist. Best-effort delete.
    try:
        op.execute("DELETE FROM workspace_attention_items WHERE target_kind = 'issue_intake'")
    except Exception:
        pass

    op.drop_index("ix_issue_work_packs_triage_task_id", table_name="issue_work_packs")
    op.drop_index("ix_issue_work_packs_status_created", table_name="issue_work_packs")
    op.drop_index("ix_issue_work_packs_project_id", table_name="issue_work_packs")
    op.drop_index("ix_issue_work_packs_launched_task_id", table_name="issue_work_packs")
    op.drop_index("ix_issue_work_packs_channel_id", table_name="issue_work_packs")
    op.drop_table("issue_work_packs")


def downgrade() -> None:
    # Recreate the table as it was at migration 282_issue_work_packs so an
    # emergency rollback can replay history. No data restoration is possible.
    op.create_table(
        "issue_work_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("category", sa.Text(), server_default=sa.text("'code_bug'"), nullable=False),
        sa.Column("confidence", sa.Text(), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column("source_item_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("launch_prompt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("triage_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("launched_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("category in ('code_bug', 'test_failure', 'config_issue', 'environment_issue', 'user_decision', 'not_code_work', 'needs_info', 'other')", name="ck_issue_work_packs_category"),
        sa.CheckConstraint("confidence in ('low', 'medium', 'high')", name="ck_issue_work_packs_confidence"),
        sa.CheckConstraint("status in ('proposed', 'launched', 'dismissed', 'needs_info')", name="ck_issue_work_packs_status"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["launched_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triage_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_issue_work_packs_channel_id", "issue_work_packs", ["channel_id"])
    op.create_index("ix_issue_work_packs_launched_task_id", "issue_work_packs", ["launched_task_id"])
    op.create_index("ix_issue_work_packs_project_id", "issue_work_packs", ["project_id"])
    op.create_index("ix_issue_work_packs_status_created", "issue_work_packs", ["status", "created_at"])
    op.create_index("ix_issue_work_packs_triage_task_id", "issue_work_packs", ["triage_task_id"])
