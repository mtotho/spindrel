"""position_history for spatial node comet-tail trails

Revision ID: 252_position_history
Revises: 251_task_layout
Create Date: 2026-04-25 21:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "252_position_history"
down_revision = "251_task_layout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_spatial_nodes",
        sa.Column(
            "position_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspace_spatial_nodes", "position_history")
