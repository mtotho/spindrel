"""Add channel_workspace_enabled to channels.

Revision ID: 115
Revises: 114
"""
from alembic import op
import sqlalchemy as sa

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("channel_workspace_enabled", sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "channel_workspace_enabled")
