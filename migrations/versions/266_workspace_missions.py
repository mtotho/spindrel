"""workspace missions

Revision ID: 266_workspace_missions
Revises: 265_unread_read_states
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "266_workspace_missions"
down_revision = "265_unread_read_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("directive", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("scope", sa.Text(), nullable=False, server_default=sa.text("'workspace'")),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("play_key", sa.Text(), nullable=True),
        sa.Column("interval_kind", sa.Text(), nullable=False, server_default=sa.text("'preset'")),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("model_override", sa.Text(), nullable=True),
        sa.Column("model_provider_id_override", sa.Text(), nullable=True),
        sa.Column("fallback_models", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("harness_effort", sa.Text(), nullable=True),
        sa.Column("history_mode", sa.Text(), nullable=True),
        sa.Column("history_recent_count", sa.Integer(), nullable=True),
        sa.Column("kickoff_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("schedule_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_update_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_run_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('active', 'paused', 'completed', 'cancelled')", name="ck_workspace_missions_status"),
        sa.CheckConstraint("scope IN ('workspace', 'channel')", name="ck_workspace_missions_scope"),
        sa.CheckConstraint("interval_kind IN ('manual', 'preset', 'custom')", name="ck_workspace_missions_interval_kind"),
        sa.CheckConstraint("history_mode IS NULL OR history_mode IN ('none', 'recent', 'full')", name="ck_workspace_missions_history_mode"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_missions_status_updated", "workspace_missions", ["status", "updated_at"])
    op.create_index("ix_workspace_missions_channel_status", "workspace_missions", ["channel_id", "status"])
    op.create_index("ix_workspace_missions_schedule_task", "workspace_missions", ["schedule_task_id"])

    op.create_table(
        "workspace_mission_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'owner'")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("target_channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_update_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["mission_id"], ["workspace_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.CheckConstraint("role IN ('owner', 'support')", name="ck_workspace_mission_assignments_role"),
        sa.CheckConstraint("status IN ('active', 'paused', 'completed', 'cancelled')", name="ck_workspace_mission_assignments_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", "bot_id", name="uq_workspace_mission_assignments_mission_bot"),
    )
    op.create_index("ix_workspace_mission_assignments_bot_status", "workspace_mission_assignments", ["bot_id", "status"])
    op.create_index("ix_workspace_mission_assignments_target_channel", "workspace_mission_assignments", ["target_channel_id"])

    op.create_table(
        "workspace_mission_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'progress'")),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("next_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["mission_id"], ["workspace_missions.id"], ondelete="CASCADE"),
        sa.CheckConstraint("kind IN ('created', 'kickoff', 'tick', 'progress', 'result', 'error', 'manual')", name="ck_workspace_mission_updates_kind"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_mission_updates_mission_created", "workspace_mission_updates", ["mission_id", "created_at"])
    op.create_index("ix_workspace_mission_updates_correlation", "workspace_mission_updates", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_mission_updates_correlation", table_name="workspace_mission_updates")
    op.drop_index("ix_workspace_mission_updates_mission_created", table_name="workspace_mission_updates")
    op.drop_table("workspace_mission_updates")
    op.drop_index("ix_workspace_mission_assignments_target_channel", table_name="workspace_mission_assignments")
    op.drop_index("ix_workspace_mission_assignments_bot_status", table_name="workspace_mission_assignments")
    op.drop_table("workspace_mission_assignments")
    op.drop_index("ix_workspace_missions_schedule_task", table_name="workspace_missions")
    op.drop_index("ix_workspace_missions_channel_status", table_name="workspace_missions")
    op.drop_index("ix_workspace_missions_status_updated", table_name="workspace_missions")
    op.drop_table("workspace_missions")
