"""Add todos table.

Revision ID: 049
Revises: 048
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "todos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True),
                  sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_todos_bot_channel_status", "todos", ["bot_id", "channel_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_todos_bot_channel_status", "todos")
    op.drop_table("todos")
