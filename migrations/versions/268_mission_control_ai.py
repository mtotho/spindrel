"""mission control ai drafts

Revision ID: 268_mission_control_ai
Revises: 267_machine_leases_replays
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "268_mission_control_ai"
down_revision = "267_machine_leases_replays"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_mission_control_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("next_focus", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("confidence", sa.Text(), nullable=False, server_default=sa.text("'medium'")),
        sa.Column("user_instruction", sa.Text(), nullable=True),
        sa.Column("grounding_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("ai_provider_id", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name="ck_workspace_mission_control_briefs_confidence"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_mission_control_briefs_created", "workspace_mission_control_briefs", ["created_at"])

    op.create_table(
        "workspace_mission_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'ai'")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("directive", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False, server_default=sa.text("'workspace'")),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("target_channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("interval_kind", sa.Text(), nullable=False, server_default=sa.text("'preset'")),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("model_override", sa.Text(), nullable=True),
        sa.Column("model_provider_id_override", sa.Text(), nullable=True),
        sa.Column("harness_effort", sa.Text(), nullable=True),
        sa.Column("grounding_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("ai_provider_id", sa.Text(), nullable=True),
        sa.Column("ai_response", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("user_instruction", sa.Text(), nullable=True),
        sa.Column("accepted_mission_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["accepted_mission_id"], ["workspace_missions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('draft', 'accepted', 'dismissed')", name="ck_workspace_mission_drafts_status"),
        sa.CheckConstraint("source IN ('ai', 'user')", name="ck_workspace_mission_drafts_source"),
        sa.CheckConstraint("scope IN ('workspace', 'channel')", name="ck_workspace_mission_drafts_scope"),
        sa.CheckConstraint("interval_kind IN ('manual', 'preset', 'custom')", name="ck_workspace_mission_drafts_interval_kind"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_mission_drafts_status_updated", "workspace_mission_drafts", ["status", "updated_at"])
    op.create_index("ix_workspace_mission_drafts_target_channel", "workspace_mission_drafts", ["target_channel_id"])
    op.create_index("ix_workspace_mission_drafts_bot", "workspace_mission_drafts", ["bot_id"])
    op.create_index("ix_workspace_mission_drafts_accepted_mission", "workspace_mission_drafts", ["accepted_mission_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_mission_drafts_accepted_mission", table_name="workspace_mission_drafts")
    op.drop_index("ix_workspace_mission_drafts_bot", table_name="workspace_mission_drafts")
    op.drop_index("ix_workspace_mission_drafts_target_channel", table_name="workspace_mission_drafts")
    op.drop_index("ix_workspace_mission_drafts_status_updated", table_name="workspace_mission_drafts")
    op.drop_table("workspace_mission_drafts")
    op.drop_index("ix_workspace_mission_control_briefs_created", table_name="workspace_mission_control_briefs")
    op.drop_table("workspace_mission_control_briefs")
