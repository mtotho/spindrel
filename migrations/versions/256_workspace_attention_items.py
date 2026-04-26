"""workspace attention items

Revision ID: 256_workspace_attention_items
Revises: 255_hb_include_pinned
Create Date: 2026-04-26 20:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "256_workspace_attention_items"
down_revision = "255_hb_include_pinned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_attention_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_kind", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'warning'")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("next_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("requires_response", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latest_correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("responded_by", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("first_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("responded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source_type IN ('bot', 'system')", name="ck_workspace_attention_source_type"),
        sa.CheckConstraint("target_kind IN ('channel', 'bot', 'widget', 'system')", name="ck_workspace_attention_target_kind"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'error', 'critical')", name="ck_workspace_attention_severity"),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'responded', 'resolved')", name="ck_workspace_attention_status"),
    )
    op.create_index("ix_workspace_attention_status_last_seen", "workspace_attention_items", ["status", "last_seen_at"])
    op.create_index("ix_workspace_attention_channel_status", "workspace_attention_items", ["channel_id", "status"])
    op.create_index("ix_workspace_attention_latest_correlation", "workspace_attention_items", ["latest_correlation_id"])
    op.create_index(
        "uq_workspace_attention_active_dedupe",
        "workspace_attention_items",
        ["source_type", "source_id", "channel_id", "target_kind", "target_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged', 'responded')"),
        sqlite_where=sa.text("status IN ('open', 'acknowledged', 'responded')"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_attention_active_dedupe", table_name="workspace_attention_items")
    op.drop_index("ix_workspace_attention_latest_correlation", table_name="workspace_attention_items")
    op.drop_index("ix_workspace_attention_channel_status", table_name="workspace_attention_items")
    op.drop_index("ix_workspace_attention_status_last_seen", table_name="workspace_attention_items")
    op.drop_table("workspace_attention_items")
