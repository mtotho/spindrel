"""Add Bot.integration_config JSONB for per-integration bot settings.

Stores integration-specific config keyed by integration id, e.g.:
  {"slack": {"icon_emoji": ":robot_face:"}}

Revision ID: 034
Revises: 033
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "integration_config",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "integration_config")
