"""Add performance indexes for tool_calls, trace_events, filesystem_chunks, tasks.

Revision ID: 160
Revises: 159
"""
import sqlalchemy as sa

from alembic import op

revision = "160"
down_revision = "159"


def upgrade() -> None:
    # ToolCall indexes
    op.create_index("ix_tool_calls_correlation_id", "tool_calls", ["correlation_id"])
    op.create_index("ix_tool_calls_bot_created", "tool_calls", ["bot_id", "created_at"])

    # TraceEvent indexes
    op.create_index("ix_trace_events_correlation_id", "trace_events", ["correlation_id"])
    op.create_index("ix_trace_events_bot_created", "trace_events", ["bot_id", "created_at"])

    # FilesystemChunk indexes
    op.create_index("ix_filesystem_chunks_bot_root", "filesystem_chunks", ["bot_id", "root"])

    # Task indexes
    op.create_index("ix_tasks_correlation_id", "tasks", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_correlation_id", table_name="tasks")
    op.drop_index("ix_filesystem_chunks_bot_root", table_name="filesystem_chunks")
    op.drop_index("ix_trace_events_bot_created", table_name="trace_events")
    op.drop_index("ix_trace_events_correlation_id", table_name="trace_events")
    op.drop_index("ix_tool_calls_bot_created", table_name="tool_calls")
    op.drop_index("ix_tool_calls_correlation_id", table_name="tool_calls")
