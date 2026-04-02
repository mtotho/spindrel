"""Add max_iterations column to channels

Revision ID: 078
Revises: 077
"""
from alembic import op
import sqlalchemy as sa

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("max_iterations", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("channels", "max_iterations")
