"""Add dispatch_mode and previous_result_max_chars to channel_heartbeats.

Revision ID: 109
Revises: 108
"""
from alembic import op
import sqlalchemy as sa

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column("dispatch_mode", sa.Text(), server_default="always", nullable=False),
    )
    op.add_column(
        "channel_heartbeats",
        sa.Column("previous_result_max_chars", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "previous_result_max_chars")
    op.drop_column("channel_heartbeats", "dispatch_mode")
