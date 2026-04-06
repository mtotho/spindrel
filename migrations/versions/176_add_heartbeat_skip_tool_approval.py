"""Add skip_tool_approval to channel_heartbeats.

Revision ID: 176
Revises: 175
"""
from alembic import op
import sqlalchemy as sa

revision = "176"
down_revision = "175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column("skip_tool_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "skip_tool_approval")
