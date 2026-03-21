"""Per-row similarity_threshold on bot_knowledge; drop bot knowledge_config similarity.

Revision ID: 037
Revises: 036
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bot_knowledge",
        sa.Column("similarity_threshold", sa.Float(), nullable=True),
    )
    op.execute(
        text(
            "UPDATE bots SET knowledge_config = knowledge_config - 'similarity_threshold'"
        )
    )


def downgrade() -> None:
    op.drop_column("bot_knowledge", "similarity_threshold")
