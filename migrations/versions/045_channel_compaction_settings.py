"""Add compaction settings to channels table.

Moves compaction configuration from bot-level to channel-level.
Bot columns kept for backward compat but no longer read by the compaction service.

Revision ID: 045
Revises: 044
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("context_compaction", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("channels", sa.Column("compaction_interval", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("compaction_keep_turns", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("compaction_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("memory_knowledge_compaction_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "memory_knowledge_compaction_prompt")
    op.drop_column("channels", "compaction_model")
    op.drop_column("channels", "compaction_keep_turns")
    op.drop_column("channels", "compaction_interval")
    op.drop_column("channels", "context_compaction")
