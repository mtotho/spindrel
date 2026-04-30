"""tool call error contract fields

Revision ID: 278_tool_call_error_contract
Revises: 277_project_run_receipts
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "278_tool_call_error_contract"
down_revision = "277_project_run_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("error_code", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("retryable", sa.Boolean(), nullable=True))
    op.add_column("tool_calls", sa.Column("retry_after_seconds", sa.Integer(), nullable=True))
    op.add_column("tool_calls", sa.Column("fallback", sa.Text(), nullable=True))
    op.create_index(
        "ix_tool_calls_error_code",
        "tool_calls",
        ["error_code"],
        postgresql_where=sa.text("error_code IS NOT NULL"),
    )
    op.create_index(
        "ix_tool_calls_retryable",
        "tool_calls",
        ["retryable"],
        postgresql_where=sa.text("retryable IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tool_calls_retryable", table_name="tool_calls")
    op.drop_index("ix_tool_calls_error_code", table_name="tool_calls")
    op.drop_column("tool_calls", "fallback")
    op.drop_column("tool_calls", "retry_after_seconds")
    op.drop_column("tool_calls", "retryable")
    op.drop_column("tool_calls", "error_code")
