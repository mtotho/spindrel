"""widget agency receipts

Revision ID: 273_widget_agency_receipts
Revises: 272_project_blueprints
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "273_widget_agency_receipts"
down_revision = "272_project_blueprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_agency_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dashboard_key", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("affected_pin_ids", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_widget_agency_receipts_channel_created",
        "widget_agency_receipts",
        ["channel_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_widget_agency_receipts_dashboard_created",
        "widget_agency_receipts",
        ["dashboard_key", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_widget_agency_receipts_correlation",
        "widget_agency_receipts",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_widget_agency_receipts_correlation", table_name="widget_agency_receipts")
    op.drop_index("ix_widget_agency_receipts_dashboard_created", table_name="widget_agency_receipts")
    op.drop_index("ix_widget_agency_receipts_channel_created", table_name="widget_agency_receipts")
    op.drop_table("widget_agency_receipts")
