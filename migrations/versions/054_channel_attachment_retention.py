"""Add per-channel attachment retention columns and retention sweep index.

Revision ID: 054
Revises: 053
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "054"
down_revision: Union[str, None] = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("attachment_retention_days", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("attachment_max_size_bytes", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("attachment_types_allowed", JSONB(), nullable=True))

    op.create_index(
        "ix_attachments_retention",
        "attachments",
        ["channel_id", "created_at"],
        postgresql_where=sa.text("file_data IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_retention", table_name="attachments")
    op.drop_column("channels", "attachment_types_allowed")
    op.drop_column("channels", "attachment_max_size_bytes")
    op.drop_column("channels", "attachment_retention_days")
