"""Convert vector indexes to halfvec (16-bit) for 50% index storage reduction.

Drops and recreates all HNSW/IVFFlat indexes with halfvec_cosine_ops casting.
Column data stays float32; only index entries use float16.

Also adds the missing HNSW index on filesystem_chunks and upgrades
conversation_sections from IVFFlat to HNSW (better for incremental writes).

Requires pgvector >= 0.7.0 (ships with pgvector/pgvector:pg16 0.8.x).

Revision ID: 157
Revises: 156
"""
from alembic import op

revision = "157"
down_revision = "156"

# (table, old_index_name, new_index_sql, old_index_sql_for_downgrade)
_CONVERSIONS = [
    # documents — HNSW → halfvec HNSW
    (
        "documents",
        "ix_documents_embedding",
        """CREATE INDEX ix_documents_embedding ON documents
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_documents_embedding ON documents
           USING hnsw (embedding vector_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
    ),
    # tool_embeddings — HNSW → halfvec HNSW
    (
        "tool_embeddings",
        "ix_tool_embeddings_embedding",
        """CREATE INDEX ix_tool_embeddings_embedding ON tool_embeddings
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_tool_embeddings_embedding ON tool_embeddings
           USING hnsw (embedding vector_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
    ),
    # conversation_sections — IVFFlat → halfvec HNSW (upgrade)
    (
        "conversation_sections",
        "ix_conversation_sections_embedding",
        """CREATE INDEX ix_conversation_sections_embedding ON conversation_sections
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_conversation_sections_embedding ON conversation_sections
           USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)""",
    ),
    # integration_documents — HNSW → halfvec HNSW
    (
        "integration_documents",
        "ix_integration_documents_embedding",
        """CREATE INDEX ix_integration_documents_embedding ON integration_documents
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_integration_documents_embedding ON integration_documents
           USING hnsw (embedding vector_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
    ),
    # memories (deprecated but still has data) — HNSW → halfvec HNSW
    (
        "memories",
        "ix_memories_embedding",
        """CREATE INDEX ix_memories_embedding ON memories
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_memories_embedding ON memories
           USING hnsw (embedding vector_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
    ),
    # bot_knowledge (deprecated but still has data) — HNSW → halfvec HNSW
    (
        "bot_knowledge",
        "ix_bot_knowledge_embedding",
        """CREATE INDEX ix_bot_knowledge_embedding ON bot_knowledge
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
        """CREATE INDEX ix_bot_knowledge_embedding ON bot_knowledge
           USING hnsw (embedding vector_cosine_ops)
           WITH (m = 16, ef_construction = 64)""",
    ),
]


def upgrade() -> None:
    # Ensure halfvec type is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Convert existing indexes to halfvec
    for table, index_name, new_sql, _ in _CONVERSIONS:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(new_sql)

    # Add NEW index on filesystem_chunks (was missing entirely)
    op.execute("DROP INDEX IF EXISTS ix_filesystem_chunks_embedding")
    op.execute(
        """CREATE INDEX ix_filesystem_chunks_embedding ON filesystem_chunks
           USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
           WITH (m = 16, ef_construction = 64)"""
    )


def downgrade() -> None:
    # Remove the new filesystem_chunks index
    op.execute("DROP INDEX IF EXISTS ix_filesystem_chunks_embedding")

    # Restore original indexes
    for table, index_name, _, old_sql in _CONVERSIONS:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
        op.execute(old_sql)
