"""Add performance indexes on high-traffic foreign keys and query patterns.

- messages.session_id: heavily queried by heartbeat and message loading
- documents.source: queried by retrieve_context()
- tool_embeddings.server_name: queried during MCP tool indexing
- tasks(status, run_at): used by task worker recovery and polling

Revision ID: 140
Revises: 139
"""

from alembic import op

revision = "140"
down_revision = "139"


def upgrade() -> None:
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_documents_source", "documents", ["source"])
    op.create_index("ix_tool_embeddings_server_name", "tool_embeddings", ["server_name"])
    op.create_index("ix_tasks_status_run_at", "tasks", ["status", "run_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_status_run_at", table_name="tasks")
    op.drop_index("ix_tool_embeddings_server_name", table_name="tool_embeddings")
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_index("ix_messages_session_id", table_name="messages")
