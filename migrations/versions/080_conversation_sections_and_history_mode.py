"""Add conversation_sections table and history_mode columns

Revision ID: 080
Revises: 079
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from pgvector.sqlalchemy import Vector

from app.config import settings

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_sections",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("period_start", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("period_end", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("transcript", sa.Text, nullable=False),
        sa.Column("message_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("embedding", Vector(settings.EMBEDDING_DIMENSIONS), nullable=True),
    )

    op.create_index("ix_conversation_sections_channel_seq", "conversation_sections", ["channel_id", "sequence"])
    op.create_index("ix_conversation_sections_session_id", "conversation_sections", ["session_id"])
    op.execute(
        "CREATE INDEX ix_conversation_sections_embedding ON conversation_sections "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
    )

    # Add history_mode to channels and bots
    op.add_column("channels", sa.Column("history_mode", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("history_mode", sa.Text(), nullable=True, server_default=sa.text("'summary'")))


def downgrade():
    op.drop_column("bots", "history_mode")
    op.drop_column("channels", "history_mode")
    op.drop_index("ix_conversation_sections_embedding", table_name="conversation_sections")
    op.drop_index("ix_conversation_sections_session_id", table_name="conversation_sections")
    op.drop_index("ix_conversation_sections_channel_seq", table_name="conversation_sections")
    op.drop_table("conversation_sections")
