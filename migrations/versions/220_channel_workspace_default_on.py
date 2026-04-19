"""Default channel_workspace_enabled to true for every channel.

Workspace is now a baseline channel feature, not an opt-in. Backfills any
NULL/false rows to true, sets server_default=true, and drops nullability so
the read path no longer has to defend against the off branch.

Revision ID: 220
Revises: 219
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "220"
down_revision = "219"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE channels SET channel_workspace_enabled = TRUE "
        "WHERE channel_workspace_enabled IS NULL OR channel_workspace_enabled = FALSE"
    )
    op.alter_column(
        "channels",
        "channel_workspace_enabled",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("true"),
    )


def downgrade() -> None:
    op.alter_column(
        "channels",
        "channel_workspace_enabled",
        existing_type=sa.Boolean(),
        nullable=True,
        server_default=None,
    )
