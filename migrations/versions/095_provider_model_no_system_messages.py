"""Add no_system_messages column to provider_models.

Revision ID: 095
Revises: 094
"""
from alembic import op
import sqlalchemy as sa

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column("no_system_messages", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("provider_models", "no_system_messages")
