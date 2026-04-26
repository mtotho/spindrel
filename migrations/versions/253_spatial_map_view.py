"""spatial map view policy and heartbeat overview

Revision ID: 253_spatial_map_view
Revises: 252_position_history
Create Date: 2026-04-26 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "253_spatial_map_view"
down_revision = "252_position_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column(
            "append_spatial_map_overview",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "append_spatial_map_overview")
