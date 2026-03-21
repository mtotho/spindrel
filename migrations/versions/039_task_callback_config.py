"""Add callback_config JSONB to tasks.

Holds orchestration state (notify_parent, parent_*, trigger_rag_loop, harness execution params)
separately from dispatch_config which is the delivery target only.

Revision ID: 039
Revises: 038
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("callback_config", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "callback_config")
