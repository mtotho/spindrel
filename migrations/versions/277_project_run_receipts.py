"""project run receipts

Revision ID: 277_project_run_receipts
Revises: 276_project_instances
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "277_project_run_receipts"
down_revision = "276_project_instances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_run_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'reported'"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("handoff_type", sa.Text(), nullable=True),
        sa.Column("handoff_url", sa.Text(), nullable=True),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("base_branch", sa.Text(), nullable=True),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("changed_files", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tests", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("screenshots", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('reported', 'completed', 'blocked', 'failed', 'needs_review')", name="ck_project_run_receipts_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_instance_id"], ["project_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_run_receipts_project_id", "project_run_receipts", ["project_id"])
    op.create_index("ix_project_run_receipts_project_instance_id", "project_run_receipts", ["project_instance_id"])
    op.create_index("ix_project_run_receipts_task_id", "project_run_receipts", ["task_id"])
    op.create_index("ix_project_run_receipts_project_created", "project_run_receipts", ["project_id", sa.text("created_at DESC")])
    op.create_index("ix_project_run_receipts_instance_created", "project_run_receipts", ["project_instance_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_project_run_receipts_instance_created", table_name="project_run_receipts")
    op.drop_index("ix_project_run_receipts_project_created", table_name="project_run_receipts")
    op.drop_index("ix_project_run_receipts_task_id", table_name="project_run_receipts")
    op.drop_index("ix_project_run_receipts_project_instance_id", table_name="project_run_receipts")
    op.drop_index("ix_project_run_receipts_project_id", table_name="project_run_receipts")
    op.drop_table("project_run_receipts")
