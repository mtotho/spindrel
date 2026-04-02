"""Add section_index_count and section_index_verbosity to channels.

Revision ID: 101
Revises: 100
"""
from alembic import op
import sqlalchemy as sa

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("section_index_count", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("section_index_verbosity", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "section_index_verbosity")
    op.drop_column("channels", "section_index_count")
