"""heartbeat execution policy

Revision ID: 250_heartbeat_execution_policy
Revises: 249_spatial_bot_presence
Create Date: 2026-04-25 10:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "250_heartbeat_execution_policy"
down_revision = "249_spatial_bot_presence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column("execution_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "execution_policy")
