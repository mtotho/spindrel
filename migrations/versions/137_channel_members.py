"""Add channel_members join table for user-channel membership.

Many-to-many between users and channels. Replaces the ownership-based
personal scope in Mission Control with explicit membership.

Backfills: every channel with a user_id gets that user as a member.

Revision ID: 137
Revises: 136
"""

import sqlalchemy as sa
from alembic import op

revision = "137"
down_revision = "136"


def upgrade() -> None:
    op.create_table(
        "channel_members",
        sa.Column("channel_id", sa.UUID(), sa.ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_channel_members_user_id", "channel_members", ["user_id"])

    # Backfill: existing channels with user_id → add creator as member
    op.execute(
        "INSERT INTO channel_members (channel_id, user_id) "
        "SELECT id, user_id FROM channels WHERE user_id IS NOT NULL "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("channel_members")
