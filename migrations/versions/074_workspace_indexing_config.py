"""Add indexing_config JSONB to shared_workspaces

Revision ID: 074
Revises: 073
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shared_workspaces",
        sa.Column("indexing_config", JSONB, nullable=True),
    )


def downgrade():
    op.drop_column("shared_workspaces", "indexing_config")
