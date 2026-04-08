"""Add supports_vision column to provider_models.

Revision ID: 180
Revises: 179
"""
from alembic import op
import sqlalchemy as sa

revision = "180"
down_revision = "179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("provider_models", "supports_vision")
