"""Add steps and step_states JSONB columns to tasks table.

Enables inline task pipelines — ordered sequences of exec/tool/agent
steps stored directly on the task, executed by the step_executor service.

Revision ID: 199
Revises: 198
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade() -> None:
    op.add_column("tasks", sa.Column("steps", JSONB, nullable=True))
    op.add_column("tasks", sa.Column("step_states", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "step_states")
    op.drop_column("tasks", "steps")
