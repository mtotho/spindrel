"""attention hub assignments

Revision ID: 258_attention_hub_assignments
Revises: 257_bot_tool_telemetry
Create Date: 2026-04-26 22:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "258_attention_hub_assignments"
down_revision = "257_bot_tool_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_workspace_attention_source_type", "workspace_attention_items", type_="check")
    op.create_check_constraint(
        "ck_workspace_attention_source_type",
        "workspace_attention_items",
        "source_type IN ('bot', 'system', 'user')",
    )
    op.add_column("workspace_attention_items", sa.Column("assigned_bot_id", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_mode", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_status", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_instructions", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assigned_by", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assigned_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_task_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_report", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_reported_by", sa.Text(), nullable=True))
    op.add_column("workspace_attention_items", sa.Column("assignment_reported_at", postgresql.TIMESTAMP(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_workspace_attention_assignment_mode",
        "workspace_attention_items",
        "assignment_mode IS NULL OR assignment_mode IN ('next_heartbeat', 'run_now')",
    )
    op.create_check_constraint(
        "ck_workspace_attention_assignment_status",
        "workspace_attention_items",
        "assignment_status IS NULL OR assignment_status IN ('assigned', 'running', 'reported', 'cancelled')",
    )
    op.create_index("ix_workspace_attention_assigned_bot", "workspace_attention_items", ["assigned_bot_id", "assignment_status"])
    op.create_index("ix_workspace_attention_assignment_task", "workspace_attention_items", ["assignment_task_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_attention_assignment_task", table_name="workspace_attention_items")
    op.drop_index("ix_workspace_attention_assigned_bot", table_name="workspace_attention_items")
    op.drop_constraint("ck_workspace_attention_assignment_status", "workspace_attention_items", type_="check")
    op.drop_constraint("ck_workspace_attention_assignment_mode", "workspace_attention_items", type_="check")
    op.drop_column("workspace_attention_items", "assignment_reported_at")
    op.drop_column("workspace_attention_items", "assignment_reported_by")
    op.drop_column("workspace_attention_items", "assignment_report")
    op.drop_column("workspace_attention_items", "assignment_task_id")
    op.drop_column("workspace_attention_items", "assigned_at")
    op.drop_column("workspace_attention_items", "assigned_by")
    op.drop_column("workspace_attention_items", "assignment_instructions")
    op.drop_column("workspace_attention_items", "assignment_status")
    op.drop_column("workspace_attention_items", "assignment_mode")
    op.drop_column("workspace_attention_items", "assigned_bot_id")
    op.drop_constraint("ck_workspace_attention_source_type", "workspace_attention_items", type_="check")
    op.create_check_constraint(
        "ck_workspace_attention_source_type",
        "workspace_attention_items",
        "source_type IN ('bot', 'system')",
    )
