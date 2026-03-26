"""Add history RAG columns to channels.

Revision ID: 087
Revises: 086
"""
from alembic import op
import sqlalchemy as sa

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column(
        "history_rag_enabled", sa.Boolean(),
        server_default=sa.text("false"), nullable=False,
    ))
    op.add_column("channels", sa.Column("history_rag_turns", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("history_rag_max_tokens", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("history_rag_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("history_rag_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "history_rag_prompt")
    op.drop_column("channels", "history_rag_model")
    op.drop_column("channels", "history_rag_max_tokens")
    op.drop_column("channels", "history_rag_turns")
    op.drop_column("channels", "history_rag_enabled")
