"""Turn feedback table + Channel.show_message_feedback toggle.

Revision ID: 295_turn_feedback
Revises: 294_session_exec_envs
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "295_turn_feedback"
down_revision = "294_session_exec_envs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "show_message_feedback",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )

    op.create_table(
        "turn_feedback",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_integration", sa.Text(), nullable=False),
        sa.Column("source_user_ref", sa.Text(), nullable=True),
        sa.Column("vote", sa.Text(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("vote IN ('up', 'down')", name="ck_turn_feedback_vote"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_turn_feedback_correlation_id", "turn_feedback", ["correlation_id"],
    )
    op.create_index(
        "ix_turn_feedback_channel_created", "turn_feedback",
        ["channel_id", "created_at"],
    )
    op.create_index(
        "uq_turn_feedback_user", "turn_feedback",
        ["correlation_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_turn_feedback_anon", "turn_feedback",
        ["correlation_id", "source_integration", "source_user_ref"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_turn_feedback_anon", table_name="turn_feedback")
    op.drop_index("uq_turn_feedback_user", table_name="turn_feedback")
    op.drop_index("ix_turn_feedback_channel_created", table_name="turn_feedback")
    op.drop_index("ix_turn_feedback_correlation_id", table_name="turn_feedback")
    op.drop_table("turn_feedback")
    op.drop_column("channels", "show_message_feedback")
