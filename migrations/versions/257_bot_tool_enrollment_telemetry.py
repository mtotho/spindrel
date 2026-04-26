"""bot_tool_enrollment fetch_count + last_used_at

Revision ID: 257_bot_tool_telemetry
Revises: 256_workspace_attention_items
Create Date: 2026-04-26 21:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "257_bot_tool_telemetry"
down_revision = "256_workspace_attention_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_tool_enrollment",
        sa.Column(
            "fetch_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "bot_tool_enrollment",
        sa.Column(
            "last_used_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bot_tool_enrollment", "last_used_at")
    op.drop_column("bot_tool_enrollment", "fetch_count")
