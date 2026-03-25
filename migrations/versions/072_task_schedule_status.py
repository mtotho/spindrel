"""Add run_count to tasks, convert existing recurring tasks to schedule templates

Revision ID: 072
Revises: 071
"""
from alembic import op
import sqlalchemy as sa

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tasks",
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # Convert existing recurring pending tasks into active schedule templates
    op.execute(
        "UPDATE tasks SET status = 'active' "
        "WHERE recurrence IS NOT NULL AND status = 'pending'"
    )

    # Normalize task_type from legacy 'recurrence' to 'scheduled'
    op.execute(
        "UPDATE tasks SET task_type = 'scheduled' "
        "WHERE task_type = 'recurrence'"
    )


def downgrade():
    # Revert active schedules back to pending
    op.execute(
        "UPDATE tasks SET status = 'pending' "
        "WHERE status = 'active' AND recurrence IS NOT NULL"
    )
    op.drop_column("tasks", "run_count")
