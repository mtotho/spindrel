"""Add per-heartbeat repetition_detection override.

Revision ID: 119
Revises: 118
"""
from alembic import op
import sqlalchemy as sa

revision = "119"
down_revision = "118"


def upgrade() -> None:
    op.add_column("channel_heartbeats", sa.Column("repetition_detection", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "repetition_detection")
