"""Add max_run_seconds columns to tasks, channels, channel_heartbeats.

Revision ID: 094
Revises: 093
"""
from alembic import op
import sqlalchemy as sa

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("max_run_seconds", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("task_max_run_seconds", sa.Integer(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column("max_run_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "max_run_seconds")
    op.drop_column("channels", "task_max_run_seconds")
    op.drop_column("tasks", "max_run_seconds")
