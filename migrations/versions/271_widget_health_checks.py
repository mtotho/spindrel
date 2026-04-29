"""widget health checks

Revision ID: 271_widget_health
Revises: 270_projects
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "271_widget_health"
down_revision = "270_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_health_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("pin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_kind", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("phases", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("event_counts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("checked_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pin_id"], ["widget_dashboard_pins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_widget_health_checks_pin_checked",
        "widget_health_checks",
        ["pin_id", sa.text("checked_at DESC")],
    )
    op.create_index(
        "ix_widget_health_checks_target_checked",
        "widget_health_checks",
        ["target_kind", "target_ref", sa.text("checked_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_widget_health_checks_target_checked", table_name="widget_health_checks")
    op.drop_index("ix_widget_health_checks_pin_checked", table_name="widget_health_checks")
    op.drop_table("widget_health_checks")
