"""heartbeat task execution config

Revision ID: 269_heartbeat_task_execution
Revises: 268_mission_control_ai
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "269_heartbeat_task_execution"
down_revision = "268_mission_control_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column("execution_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "heartbeat_runs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_heartbeat_runs_task_id_tasks",
        "heartbeat_runs",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_heartbeat_runs_task_id", "heartbeat_runs", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_heartbeat_runs_task_id", table_name="heartbeat_runs")
    op.drop_constraint("fk_heartbeat_runs_task_id_tasks", "heartbeat_runs", type_="foreignkey")
    op.drop_column("heartbeat_runs", "task_id")
    op.drop_column("channel_heartbeats", "execution_config")
