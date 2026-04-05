"""Add config JSONB column to channel_bot_members

Revision ID: 165
Revises: 164
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "165"
down_revision = "164"


def upgrade() -> None:
    op.add_column(
        "channel_bot_members",
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channel_bot_members", "config")
