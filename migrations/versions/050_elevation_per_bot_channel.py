"""Add elevation fields to bots and channels.

Revision ID: 050
Revises: 049
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("elevation_enabled", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("elevation_threshold", sa.Float(), nullable=True))
    op.add_column("bots", sa.Column("elevated_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("elevation_enabled", sa.Boolean(), nullable=True))
    op.add_column("channels", sa.Column("elevation_threshold", sa.Float(), nullable=True))
    op.add_column("channels", sa.Column("elevated_model", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "elevated_model")
    op.drop_column("channels", "elevation_threshold")
    op.drop_column("channels", "elevation_enabled")
    op.drop_column("bots", "elevated_model")
    op.drop_column("bots", "elevation_threshold")
    op.drop_column("bots", "elevation_enabled")
