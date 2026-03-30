"""Compaction logs table for visibility into compaction events.

Revision ID: 118
Revises: 117
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "118"
down_revision = "117"


def upgrade() -> None:
    op.create_table(
        "compaction_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("history_mode", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("memory_flush", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("messages_archived", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("section_id", UUID(as_uuid=True), sa.ForeignKey("conversation_sections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_compaction_logs_channel_created", "compaction_logs", ["channel_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_compaction_logs_channel_created", "compaction_logs")
    op.drop_table("compaction_logs")
