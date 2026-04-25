"""task layout for pipeline canvas tab

Revision ID: 251_task_layout
Revises: 250_heartbeat_execution_policy
Create Date: 2026-04-25 19:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "251_task_layout"
down_revision = "250_heartbeat_execution_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "layout",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "layout")
