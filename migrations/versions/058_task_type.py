"""Add task_type column to tasks table.

Revision ID: 058
Revises: 057
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("task_type", sa.Text(), nullable=False, server_default="agent"),
    )

    # Backfill existing rows based on heuristics
    op.execute("""
        UPDATE tasks SET task_type = 'scheduled'
        WHERE recurrence IS NOT NULL
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'heartbeat'
        WHERE task_type = 'agent'
          AND callback_config->>'source' = 'heartbeat'
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'harness'
        WHERE task_type = 'agent'
          AND dispatch_type = 'harness'
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'exec'
        WHERE task_type = 'agent'
          AND dispatch_type = 'exec'
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'callback'
        WHERE task_type = 'agent'
          AND callback_config->>'notify_parent' = 'true'
    """)


def downgrade() -> None:
    op.drop_column("tasks", "task_type")
