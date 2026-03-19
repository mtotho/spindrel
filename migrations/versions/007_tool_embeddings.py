"""Tool schema embeddings for dynamic tool selection (RAG).

Revision ID: 007
Revises: 006
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_embeddings",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tool_key", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("server_name", sa.Text(), nullable=True),
        sa.Column("source_dir", sa.Text(), nullable=True),
        sa.Column("schema", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column(
            "indexed_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_tool_embeddings_tool_key", "tool_embeddings", ["tool_key"])
    op.create_index("ix_tool_embeddings_tool_name", "tool_embeddings", ["tool_name"])
    op.create_index("ix_tool_embeddings_server_name", "tool_embeddings", ["server_name"])
    op.create_index("ix_tool_embeddings_content_hash", "tool_embeddings", ["content_hash"])
    op.create_index(
        "ix_tool_embeddings_embedding",
        "tool_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("tool_embeddings")
