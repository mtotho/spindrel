"""Add source column to tasks table.

Distinguishes user-authored tasks from system-seeded pipelines loaded
from ``app/data/system_pipelines/`` YAML files. System pipelines are
refreshed from YAML on boot; user pipelines are never overwritten.

Revision ID: 202
Revises: 201
"""
from alembic import op
import sqlalchemy as sa

revision = "202"
down_revision = "201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'user'")),
    )


def downgrade() -> None:
    op.drop_column("tasks", "source")
