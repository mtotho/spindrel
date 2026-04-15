"""Add trigger_config JSONB column to tasks table.

Stores trigger metadata for event-based and manual task triggers.
Schedule triggers continue to use the existing scheduled_at + recurrence
fields; this column captures the trigger type and event filter config.

Revision ID: 197
Revises: 196
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "197"
down_revision = "196"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("trigger_config", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "trigger_config")
