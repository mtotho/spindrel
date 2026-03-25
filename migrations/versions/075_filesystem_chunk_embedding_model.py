"""Add embedding_model column to filesystem_chunks

Revision ID: 075
Revises: 074
"""
from alembic import op
import sqlalchemy as sa

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "filesystem_chunks",
        sa.Column("embedding_model", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("filesystem_chunks", "embedding_model")
