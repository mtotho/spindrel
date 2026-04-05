"""Add GIN index on tool_embeddings.embed_text for BM25 full-text search.

Revision ID: 168
Revises: 167
"""

from alembic import op

revision = "168"
down_revision = "167"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tool_embeddings_fts "
        "ON tool_embeddings USING GIN (to_tsvector('english', embed_text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tool_embeddings_fts")
