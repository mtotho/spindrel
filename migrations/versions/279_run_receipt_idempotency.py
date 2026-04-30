"""project run receipt idempotency

Revision ID: 279_run_receipt_idempotency
Revises: 278_tool_call_error_contract
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op


revision = "279_run_receipt_idempotency"
down_revision = "278_tool_call_error_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE project_run_receipts "
        "ADD COLUMN IF NOT EXISTS idempotency_key TEXT"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_project_run_receipts_project_idempotency "
        "ON project_run_receipts (project_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_project_run_receipts_project_idempotency")
    op.execute(
        "ALTER TABLE project_run_receipts DROP COLUMN IF EXISTS idempotency_key"
    )
