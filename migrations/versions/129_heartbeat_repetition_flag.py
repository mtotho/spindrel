"""Add repetition_detected flag to heartbeat_runs.

Revision ID: 129
Revises: 128
"""

from alembic import op
import sqlalchemy as sa


revision = "129"
down_revision = "128"


def upgrade() -> None:
    op.add_column(
        "heartbeat_runs",
        sa.Column("repetition_detected", sa.Boolean, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("heartbeat_runs", "repetition_detected")
