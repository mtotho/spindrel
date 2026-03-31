"""Add performance indexes to tasks, tool_calls, trace_events, and messages.

These tables were missing indexes on commonly-queried columns:
- tasks(status, scheduled_at): polled every 5s by the task worker
- tool_calls(correlation_id): used by heartbeat repetition detection
- trace_events(correlation_id): used by admin trace queries
- messages(session_id, created_at): used by every chat request to load history

Revision ID: 135
Revises: 134
"""

from alembic import op
from sqlalchemy import text

revision = "135"
down_revision = "134"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_status_scheduled_at ON tasks (status, scheduled_at)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tool_calls_correlation_id ON tool_calls (correlation_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_trace_events_correlation_id ON trace_events (correlation_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_session_id_created_at ON messages (session_id, created_at)"))


def downgrade() -> None:
    op.drop_index("ix_messages_session_id_created_at", table_name="messages")
    op.drop_index("ix_trace_events_correlation_id", table_name="trace_events")
    op.drop_index("ix_tool_calls_correlation_id", table_name="tool_calls")
    op.drop_index("ix_tasks_status_scheduled_at", table_name="tasks")
