"""bot_knowledge.session_id: ON DELETE SET NULL (keep rows when session deleted).

Revision ID: 036
Revises: 035
"""
from __future__ import annotations

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_bot_knowledge_session_id", "bot_knowledge", type_="foreignkey")
    op.create_foreign_key(
        "fk_bot_knowledge_session_id",
        "bot_knowledge",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bot_knowledge_session_id", "bot_knowledge", type_="foreignkey")
    op.create_foreign_key(
        "fk_bot_knowledge_session_id",
        "bot_knowledge",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
