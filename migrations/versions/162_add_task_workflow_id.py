"""Add workflow_id and workflow_session_mode to tasks table.

Revision ID: 162
Revises: 161
"""

from alembic import op
import sqlalchemy as sa

revision = "162"
down_revision = "161"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("workflow_id", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("workflow_session_mode", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "workflow_session_mode")
    op.drop_column("tasks", "workflow_id")
