"""Add integration_documents table and dispatch_config to sessions.

Revision ID: 031
Revises: 030
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_documents",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("integration_id", sa.Text(), nullable=True),
        sa.Column(
            "session_id",
            sa.UUID(),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("metadata", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_integration_documents_integration_id", "integration_documents", ["integration_id"])
    op.create_index("ix_integration_documents_session_id", "integration_documents", ["session_id"])
    op.create_index(
        "ix_integration_documents_embedding",
        "integration_documents",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.add_column("sessions", sa.Column("dispatch_config", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "dispatch_config")
    op.drop_table("integration_documents")
