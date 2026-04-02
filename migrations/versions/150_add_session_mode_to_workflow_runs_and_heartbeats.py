"""Add session_mode to workflow_runs and workflow_session_mode to channel_heartbeats.

Revision ID: 150
Revises: 149
"""
import sqlalchemy as sa
from alembic import op

revision = "150"
down_revision = "149"


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("session_mode", sa.Text, nullable=False, server_default="isolated"),
    )
    op.add_column(
        "channel_heartbeats",
        sa.Column("workflow_session_mode", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "session_mode")
    op.drop_column("channel_heartbeats", "workflow_session_mode")
