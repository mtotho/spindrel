"""Add index on channel_bot_members.bot_id for member-channel lookups.

Revision ID: 173
Revises: 172
"""
from alembic import op

revision = "173"
down_revision = "172"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_channel_bot_members_bot_id", "channel_bot_members", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_bot_members_bot_id", table_name="channel_bot_members")
