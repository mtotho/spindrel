"""project run receipt idempotency

Revision ID: 279_project_run_receipt_idempotency
Revises: 278_tool_call_error_contract
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "279_project_run_receipt_idempotency"
down_revision = "278_tool_call_error_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project_run_receipts", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.create_index(
        "ux_project_run_receipts_project_idempotency",
        "project_run_receipts",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_project_run_receipts_project_idempotency", table_name="project_run_receipts")
    op.drop_column("project_run_receipts", "idempotency_key")
