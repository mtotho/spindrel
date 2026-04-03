"""Add performance indexes for tool_calls, trace_events, filesystem_chunks, tasks.

Revision ID: 160
Revises: 159
"""
from alembic import op

revision = "160"
down_revision = "159"


def upgrade() -> None:
    # ToolCall indexes (correlation_id may exist from 009/135, bot_created from 104)
    op.create_index("ix_tool_calls_correlation_id", "tool_calls", ["correlation_id"], if_not_exists=True)
    op.create_index("ix_tool_calls_bot_created", "tool_calls", ["bot_id", "created_at"], if_not_exists=True)

    # TraceEvent indexes (correlation_id may exist from 009/135)
    op.create_index("ix_trace_events_correlation_id", "trace_events", ["correlation_id"], if_not_exists=True)
    op.create_index("ix_trace_events_bot_created", "trace_events", ["bot_id", "created_at"], if_not_exists=True)

    # FilesystemChunk indexes
    op.create_index("ix_filesystem_chunks_bot_root", "filesystem_chunks", ["bot_id", "root"], if_not_exists=True)

    # Task indexes
    op.create_index("ix_tasks_correlation_id", "tasks", ["correlation_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_tasks_correlation_id", table_name="tasks", if_exists=True)
    op.drop_index("ix_filesystem_chunks_bot_root", table_name="filesystem_chunks", if_exists=True)
    op.drop_index("ix_trace_events_bot_created", table_name="trace_events", if_exists=True)
    op.drop_index("ix_trace_events_correlation_id", table_name="trace_events", if_exists=True)
    op.drop_index("ix_tool_calls_bot_created", table_name="tool_calls", if_exists=True)
    op.drop_index("ix_tool_calls_correlation_id", table_name="tool_calls", if_exists=True)
