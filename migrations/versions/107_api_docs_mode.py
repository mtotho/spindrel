"""Add api_docs_mode column to bots.

Revision ID: 107
Revises: 106
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("api_docs_mode", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "api_docs_mode")
