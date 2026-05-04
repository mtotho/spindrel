"""drop user-scope knowledge document index entries

Revision ID: 297_drop_user_knowledge_chunks
Revises: 296_drop_demoted_audit_pipelines
Create Date: 2026-05-03

Removes ``filesystem_chunks`` rows for the retired
``users/<user_id>/knowledge-base/notes/`` per-turn capture path. The
parallel user-knowledge store landed as the original Phase 1 of the
User Knowledge Graph track and is being replaced by semantic retrieval
over the bot-curated ``memory/reference/`` libraries — see
``docs/plans/user-knowledge-graph.md`` for the rationale.
"""
from __future__ import annotations

from alembic import op


revision = "297_drop_user_knowledge_chunks"
down_revision = "296_drop_demoted_audit_pipelines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM filesystem_chunks "
        "WHERE bot_id IS NULL "
        "AND client_id IS NULL "
        "AND file_path LIKE 'users/%/knowledge-base/notes/%'"
    )


def downgrade() -> None:
    # Index entries are derived from filesystem content; the indexer
    # rebuilds them when the source files exist. The retired capture
    # path no longer writes any source files, so a downgrade has
    # nothing to restore.
    pass
