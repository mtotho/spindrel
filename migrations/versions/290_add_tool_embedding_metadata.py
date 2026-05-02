"""Add metadata to tool embeddings for generic routing policy.

Revision ID: 290_add_tool_embedding_metadata
Revises: 289_add_manifest_signature
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "290_add_tool_embedding_metadata"
down_revision = "289_add_manifest_signature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_embeddings",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tool_embeddings", "metadata")

