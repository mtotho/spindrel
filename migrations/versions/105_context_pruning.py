"""Add context_pruning columns to bots and channels.

Revision ID: 105
Revises: 104
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("context_pruning", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("context_pruning_keep_turns", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("context_pruning", sa.Boolean(), nullable=True))
    op.add_column("channels", sa.Column("context_pruning_keep_turns", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "context_pruning_keep_turns")
    op.drop_column("channels", "context_pruning")
    op.drop_column("bots", "context_pruning_keep_turns")
    op.drop_column("bots", "context_pruning")
