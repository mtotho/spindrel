"""Add context compression config to bots and channels.

Revision ID: 056
Revises: 055
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "056"
down_revision: Union[str, None] = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("compression_config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "channels",
        sa.Column("context_compression", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("compression_model", sa.Text(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("compression_threshold", sa.Integer(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("compression_keep_turns", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channels", "compression_keep_turns")
    op.drop_column("channels", "compression_threshold")
    op.drop_column("channels", "compression_model")
    op.drop_column("channels", "context_compression")
    op.drop_column("bots", "compression_config")
