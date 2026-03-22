"""Add image_id column to sandbox_instances.

Revision ID: 048
Revises: 047
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("sandbox_instances", sa.Column("image_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sandbox_instances", "image_id")
