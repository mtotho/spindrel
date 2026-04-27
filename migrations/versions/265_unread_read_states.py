"""unread read states

Revision ID: 265_unread_read_states
Revises: 264_pin_source_stamp
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "265_unread_read_states"
down_revision = "264_pin_source_stamp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_heartbeats", sa.Column("harness_effort", sa.Text(), nullable=True))

    op.create_table(
        "session_read_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_read_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_read_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_read_source", sa.Text(), nullable=True),
        sa.Column("last_read_surface", sa.Text(), nullable=True),
        sa.Column("first_unread_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("latest_unread_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("latest_unread_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("latest_unread_correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unread_agent_reply_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("initial_notified_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reminder_due_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_read_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["latest_unread_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", "session_id", name="uq_session_read_states_user_session"),
    )
    op.create_index("ix_session_read_states_user", "session_read_states", ["user_id"])
    op.create_index("ix_session_read_states_session", "session_read_states", ["session_id"])
    op.create_index("ix_session_read_states_channel", "session_read_states", ["channel_id"])
    op.create_index("ix_session_read_states_user_unread", "session_read_states", ["user_id", "unread_agent_reply_count"])
    op.create_index("ix_session_read_states_reminder_due", "session_read_states", ["reminder_due_at"])

    op.create_table(
        "unread_notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("target_mode", sa.Text(), nullable=False, server_default=sa.text("'inherit'")),
        sa.Column("target_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("immediate_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("reminder_delay_minutes", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("preview_policy", sa.Text(), nullable=False, server_default=sa.text("'short'")),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.CheckConstraint("target_mode IN ('inherit', 'replace')", name="ck_unread_notification_rules_target_mode"),
        sa.CheckConstraint("preview_policy IN ('none', 'short', 'full')", name="ck_unread_notification_rules_preview_policy"),
        sa.UniqueConstraint("user_id", "channel_id", name="uq_unread_notification_rules_user_channel"),
    )
    op.create_index("ix_unread_notification_rules_user", "unread_notification_rules", ["user_id"])
    op.create_index("ix_unread_notification_rules_channel", "unread_notification_rules", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_unread_notification_rules_channel", table_name="unread_notification_rules")
    op.drop_index("ix_unread_notification_rules_user", table_name="unread_notification_rules")
    op.drop_table("unread_notification_rules")
    op.drop_index("ix_session_read_states_reminder_due", table_name="session_read_states")
    op.drop_index("ix_session_read_states_user_unread", table_name="session_read_states")
    op.drop_index("ix_session_read_states_channel", table_name="session_read_states")
    op.drop_index("ix_session_read_states_session", table_name="session_read_states")
    op.drop_index("ix_session_read_states_user", table_name="session_read_states")
    op.drop_table("session_read_states")
    op.drop_column("channel_heartbeats", "harness_effort")
