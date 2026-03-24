"""Add quiet hours fields to channel_heartbeats.

Revision ID: 059
Revises: 058
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_heartbeats", sa.Column("quiet_start", sa.Time(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column("quiet_end", sa.Time(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column("timezone", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "timezone")
    op.drop_column("channel_heartbeats", "quiet_end")
    op.drop_column("channel_heartbeats", "quiet_start")
