"""Heartbeat decoupling: add tracking columns and heartbeat_runs history table.

Revision ID: 088
Revises: 087
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP, JSONB

revision = "088"
down_revision = "087"


def upgrade() -> None:
    # Add tracking columns to channel_heartbeats
    op.add_column("channel_heartbeats", sa.Column("last_result", sa.Text(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column("run_count", sa.Integer(), server_default="0", nullable=False))

    # Create heartbeat_runs history table
    op.create_table(
        "heartbeat_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("heartbeat_id", UUID(as_uuid=True), sa.ForeignKey("channel_heartbeats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_at", TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
    )
    op.create_index("ix_heartbeat_runs_heartbeat_id", "heartbeat_runs", ["heartbeat_id"])
    op.create_index("ix_heartbeat_runs_run_at", "heartbeat_runs", ["run_at"])


def downgrade() -> None:
    op.drop_table("heartbeat_runs")
    op.drop_column("channel_heartbeats", "run_count")
    op.drop_column("channel_heartbeats", "last_error")
    op.drop_column("channel_heartbeats", "last_result")
