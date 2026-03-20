"""Correlation ID + unified trace logging.

Revision ID: 009
Revises: 008
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add correlation_id to existing tables
    op.add_column("tool_calls", sa.Column("correlation_id", sa.UUID(), nullable=True))
    op.create_index("ix_tool_calls_correlation_id", "tool_calls", ["correlation_id"])

    op.add_column("messages", sa.Column("correlation_id", sa.UUID(), nullable=True))
    op.create_index("ix_messages_correlation_id", "messages", ["correlation_id"])

    op.add_column("memories", sa.Column("correlation_id", sa.UUID(), nullable=True))

    # New table: trace_events
    op.create_table(
        "trace_events",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("data", JSONB(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_trace_events_correlation_id", "trace_events", ["correlation_id"])
    op.create_index("ix_trace_events_session_id", "trace_events", ["session_id"])
    op.create_index("ix_trace_events_created_at", "trace_events", ["created_at"])

    # New table: knowledge_writes
    op.create_table(
        "knowledge_writes",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("knowledge_name", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_knowledge_writes_correlation_id", "knowledge_writes", ["correlation_id"])
    op.create_index(
        "ix_knowledge_writes_name_bot_client_at",
        "knowledge_writes",
        ["knowledge_name", "bot_id", "client_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_writes")
    op.drop_table("trace_events")
    op.drop_column("memories", "correlation_id")
    op.drop_index("ix_messages_correlation_id", table_name="messages")
    op.drop_column("messages", "correlation_id")
    op.drop_index("ix_tool_calls_correlation_id", table_name="tool_calls")
    op.drop_column("tool_calls", "correlation_id")
