"""Integration settings table for DB-backed integration config.

Revision ID: 120
Revises: 119
"""
from alembic import op
import sqlalchemy as sa

revision = "120"
down_revision = "119"


def upgrade() -> None:
    op.create_table(
        "integration_settings",
        sa.Column("integration_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("integration_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("integration_settings")
