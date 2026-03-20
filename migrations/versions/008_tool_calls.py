"""Tool call logging table.

Revision ID: 008
Revises: 007
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_calls",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.Text(), nullable=False),  # "local" | "mcp" | "client"
        sa.Column("server_name", sa.Text(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("arguments", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # FK is intentionally not enforced (sessions can be deleted independently)
    op.create_index("ix_tool_calls_session_id_created_at", "tool_calls", ["session_id", "created_at"])
    op.create_index("ix_tool_calls_tool_name_created_at", "tool_calls", ["tool_name", "created_at"])
    op.create_index("ix_tool_calls_bot_id", "tool_calls", ["bot_id"])
    op.create_index("ix_tool_calls_created_at", "tool_calls", ["created_at"])


def downgrade() -> None:
    op.drop_table("tool_calls")
