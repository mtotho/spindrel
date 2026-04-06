"""Add memory_hygiene_target_hour to bots table.

Revision ID: 178
Revises: 177
"""
from alembic import op
import sqlalchemy as sa

revision = "178"
down_revision = "177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("memory_hygiene_target_hour", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "memory_hygiene_target_hour")
