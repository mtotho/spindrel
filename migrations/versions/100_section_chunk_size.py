"""Add chunk_size column to conversation_sections.

Revision ID: 100
Revises: 099
"""
from alembic import op
import sqlalchemy as sa

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_sections",
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default=sa.text("50")),
    )


def downgrade() -> None:
    op.drop_column("conversation_sections", "chunk_size")
