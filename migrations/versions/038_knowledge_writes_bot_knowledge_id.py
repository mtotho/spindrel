"""Bind knowledge_writes to bot_knowledge.id (required FK).

Revision ID: 038
Revises: 037
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_writes",
        sa.Column("bot_knowledge_id", UUID(as_uuid=True), nullable=True),
    )
    op.execute(text("DELETE FROM knowledge_writes"))
    op.alter_column("knowledge_writes", "bot_knowledge_id", nullable=False)
    op.create_foreign_key(
        "fk_knowledge_writes_bot_knowledge_id",
        "knowledge_writes",
        "bot_knowledge",
        ["bot_knowledge_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_knowledge_writes_bot_knowledge_id",
        "knowledge_writes",
        ["bot_knowledge_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_writes_bot_knowledge_id", table_name="knowledge_writes")
    op.drop_constraint(
        "fk_knowledge_writes_bot_knowledge_id",
        "knowledge_writes",
        type_="foreignkey",
    )
    op.drop_column("knowledge_writes", "bot_knowledge_id")
