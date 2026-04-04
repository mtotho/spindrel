"""Add channel_bot_members table for multi-bot channels

Revision ID: 164
Revises: 163
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "164"
down_revision = "163"


def upgrade() -> None:
    op.create_table(
        "channel_bot_members",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_channel_bot_members_channel_bot", "channel_bot_members", ["channel_id", "bot_id"])
    op.create_index("ix_channel_bot_members_channel_id", "channel_bot_members", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_bot_members_channel_id")
    op.drop_constraint("uq_channel_bot_members_channel_bot", "channel_bot_members")
    op.drop_table("channel_bot_members")
