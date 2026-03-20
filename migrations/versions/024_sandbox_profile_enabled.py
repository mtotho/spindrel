"""Add enabled column to sandbox_profiles table.

Revision ID: 024
Revises: 023
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sandbox_profiles",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("sandbox_profiles", "enabled")
