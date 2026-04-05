"""Add capability_embeddings table for capability RAG index.

Revision ID: 171
Revises: 170
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "171"
down_revision = "170"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_embeddings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("carapace_id", sa.Text(), unique=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("indexed_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    # HNSW index for fast cosine similarity queries
    op.execute(
        "CREATE INDEX ix_capability_embeddings_hnsw ON capability_embeddings "
        "USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_capability_embeddings_hnsw")
    op.drop_table("capability_embeddings")
