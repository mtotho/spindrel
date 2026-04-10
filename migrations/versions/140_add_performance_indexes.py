"""Add performance indexes on high-traffic foreign keys and query patterns.

- messages.session_id: heavily queried by heartbeat and message loading
- documents.source: queried by retrieve_skill_index() / fetch_skill_chunks_by_id()
- tool_embeddings.server_name: queried during MCP tool indexing
- tasks(status, run_at): used by task worker recovery and polling

Revision ID: 140
Revises: 139
"""

import sqlalchemy as sa
from alembic import op

revision = "140"
down_revision = "139"


def upgrade() -> None:
    # Use IF NOT EXISTS to handle indexes that may already exist (e.g. from
    # SQLAlchemy's __table_args__ auto-creation or a partially-applied migration).
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages (session_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_documents_source ON documents (source)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tool_embeddings_server_name ON tool_embeddings (server_name)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_tasks_status_run_at ON tasks (status, run_at)"))


def downgrade() -> None:
    op.drop_index("ix_tasks_status_run_at", table_name="tasks")
    op.drop_index("ix_tool_embeddings_server_name", table_name="tool_embeddings")
    op.drop_index("ix_documents_source", table_name="documents")
    op.drop_index("ix_messages_session_id", table_name="messages")
