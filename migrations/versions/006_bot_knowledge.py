"""Add bot_knowledge table for per-client knowledge documents (vector search).

Revision ID: 006
Revises: 005
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_knowledge",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("created_by_bot", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_knowledge_name_scope",
        "bot_knowledge",
        ["name", "bot_id", "client_id"],
    )
    op.create_index(
        "ix_bot_knowledge_embedding",
        "bot_knowledge",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_bot_knowledge_client_id", "bot_knowledge", ["client_id"])
    op.create_index("ix_bot_knowledge_bot_id", "bot_knowledge", ["bot_id"])


def downgrade() -> None:
    op.drop_table("bot_knowledge")
