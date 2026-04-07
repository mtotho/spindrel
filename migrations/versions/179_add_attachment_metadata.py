"""Add metadata JSONB column to attachments table.

Revision ID: 179
Revises: 178
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "179"
down_revision = "178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("attachments", "metadata")
