"""Add source_type column to bots table.

Revision ID: 153
Revises: 152
"""
from alembic import op
import sqlalchemy as sa

revision = "153"
down_revision = "152"


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
    )


def downgrade() -> None:
    op.drop_column("bots", "source_type")
