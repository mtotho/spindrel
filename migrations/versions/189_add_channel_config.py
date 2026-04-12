"""Add config JSONB column to channels table.

Phase B of Rich Tool Rendering: pinned workspace-file panels.
Stores per-channel configuration like pinned_panels list.

Revision ID: 189
Revises: 188
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "189"
down_revision: Union[str, None] = "188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("config", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channels", "config")
