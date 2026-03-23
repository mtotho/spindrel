"""Add file_data BYTEA column to attachments, make url nullable.

Revision ID: 053
Revises: 052
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "053"
down_revision: Union[str, None] = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("file_data", sa.LargeBinary(), nullable=True))
    op.alter_column("attachments", "url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("attachments", "url", existing_type=sa.Text(), nullable=False)
    op.drop_column("attachments", "file_data")
