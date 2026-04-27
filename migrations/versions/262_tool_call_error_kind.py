"""tool_call error_kind

Revision ID: 262_tool_call_error_kind
Revises: 261_notification_targets
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "262_tool_call_error_kind"
down_revision = "261_notification_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("error_kind", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_tool_calls_error_kind",
        "tool_calls",
        ["error_kind"],
        postgresql_where=sa.text("error_kind IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tool_calls_error_kind", table_name="tool_calls")
    op.drop_column("tool_calls", "error_kind")
