"""Add title column to tasks

Revision ID: 079
Revises: 078
"""
from alembic import op
import sqlalchemy as sa

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("title", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("tasks", "title")
