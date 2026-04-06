"""Add memory_hygiene_model columns to bots table.

Revision ID: 175
Revises: 174
"""
from alembic import op
import sqlalchemy as sa

revision = "175"
down_revision = "174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("memory_hygiene_model", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("memory_hygiene_model_provider_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "memory_hygiene_model_provider_id")
    op.drop_column("bots", "memory_hygiene_model")
