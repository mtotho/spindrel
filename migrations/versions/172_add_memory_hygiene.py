"""Add memory hygiene columns to bots table.

Revision ID: 172
Revises: 171
"""
import sqlalchemy as sa
from alembic import op

revision = "172"
down_revision = "171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("memory_hygiene_enabled", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("memory_hygiene_interval_hours", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("memory_hygiene_prompt", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("memory_hygiene_only_if_active", sa.Boolean(), nullable=True))
    op.add_column(
        "bots",
        sa.Column(
            "last_hygiene_run_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "bots",
        sa.Column(
            "next_hygiene_run_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "next_hygiene_run_at")
    op.drop_column("bots", "last_hygiene_run_at")
    op.drop_column("bots", "memory_hygiene_only_if_active")
    op.drop_column("bots", "memory_hygiene_prompt")
    op.drop_column("bots", "memory_hygiene_interval_hours")
    op.drop_column("bots", "memory_hygiene_enabled")
