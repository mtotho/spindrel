"""system health summaries

Revision ID: 259_system_health_summaries
Revises: 258_attention_hub_assignments
Create Date: 2026-04-26 23:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "259_system_health_summaries"
down_revision = "258_attention_hub_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_health_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("period_start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_end", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("generated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attention_item_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("trace_event_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tool_error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("attention_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_system_health_summaries_generated_at",
        "system_health_summaries",
        [sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_system_health_summaries_generated_at", table_name="system_health_summaries")
    op.drop_table("system_health_summaries")
