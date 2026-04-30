"""execution receipts

Revision ID: 280_execution_receipts
Revises: 279_run_receipt_idempotency
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "280_execution_receipts"
down_revision = "279_run_receipt_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scope", sa.Text(), server_default=sa.text("'general'"), nullable=False),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'reported'"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("before_summary", sa.Text(), nullable=True),
        sa.Column("after_summary", sa.Text(), nullable=True),
        sa.Column("approval_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("approval_ref", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("rollback_hint", sa.Text(), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('reported', 'succeeded', 'failed', 'blocked', 'needs_review')",
            name="ck_execution_receipts_status",
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_execution_receipts_scope_created",
        "execution_receipts",
        ["scope", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_execution_receipts_bot_created",
        "execution_receipts",
        ["bot_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_execution_receipts_channel_created",
        "execution_receipts",
        ["channel_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_execution_receipts_correlation", "execution_receipts", ["correlation_id"])
    op.create_index(
        "ux_execution_receipts_scope_idempotency",
        "execution_receipts",
        ["scope", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_execution_receipts_scope_idempotency", table_name="execution_receipts")
    op.drop_index("ix_execution_receipts_correlation", table_name="execution_receipts")
    op.drop_index("ix_execution_receipts_channel_created", table_name="execution_receipts")
    op.drop_index("ix_execution_receipts_bot_created", table_name="execution_receipts")
    op.drop_index("ix_execution_receipts_scope_created", table_name="execution_receipts")
    op.drop_table("execution_receipts")
