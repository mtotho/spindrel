"""Session-scoped bot_knowledge rows; partial unique indexes.

Revision ID: 035
Revises: 034
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_knowledge",
        sa.Column("session_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bot_knowledge_session_id",
        "bot_knowledge",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("uq_knowledge_name_scope", "bot_knowledge", type_="unique")
    op.create_index(
        "uq_bot_knowledge_legacy_scope",
        "bot_knowledge",
        ["name", "bot_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NULL"),
    )
    op.create_index(
        "uq_bot_knowledge_session_scope",
        "bot_knowledge",
        ["name", "bot_id", "client_id", "session_id"],
        unique=True,
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.create_index("ix_bot_knowledge_session_id", "bot_knowledge", ["session_id"])

    op.add_column(
        "knowledge_writes",
        sa.Column("session_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_writes", "session_id")
    op.drop_index("ix_bot_knowledge_session_id", table_name="bot_knowledge")
    op.drop_index("uq_bot_knowledge_session_scope", table_name="bot_knowledge")
    op.drop_index("uq_bot_knowledge_legacy_scope", table_name="bot_knowledge")
    op.drop_constraint("fk_bot_knowledge_session_id", "bot_knowledge", type_="foreignkey")
    op.drop_column("bot_knowledge", "session_id")
    op.create_unique_constraint(
        "uq_knowledge_name_scope",
        "bot_knowledge",
        ["name", "bot_id", "client_id"],
    )
