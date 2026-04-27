"""heartbeat runner mode

Revision ID: 260_heartbeat_runner_mode
Revises: 259_system_health_summaries
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "260_heartbeat_runner_mode"
down_revision = "259_system_health_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_heartbeats", sa.Column("runner_mode", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "runner_mode")
