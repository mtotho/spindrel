"""Add channel_skill_enrollment table.

Revision ID: 236
Revises: 235
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "236"
down_revision = "235"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_skill_enrollment",
        sa.Column("channel_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("enrolled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "skill_id"),
    )


def downgrade() -> None:
    op.drop_table("channel_skill_enrollment")
