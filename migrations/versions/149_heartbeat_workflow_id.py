"""Add workflow_id to channel_heartbeats for direct workflow triggering.

Revision ID: 149
Revises: 148
"""
import sqlalchemy as sa
from alembic import op

revision = "149"
down_revision = "148"


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column("workflow_id", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "workflow_id")
