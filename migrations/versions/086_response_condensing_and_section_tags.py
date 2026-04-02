"""Add response condensing columns, drop summarizer columns, add condensed to messages, add tags to conversation_sections.

Revision ID: 086
Revises: 085
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Message: add condensed column ---
    op.add_column("messages", sa.Column("condensed", sa.Text(), nullable=True))

    # --- ConversationSection: add tags column ---
    op.add_column("conversation_sections", sa.Column("tags", JSONB(), nullable=True))

    # --- Channel: add response_condensing columns ---
    op.add_column("channels", sa.Column(
        "response_condensing_enabled", sa.Boolean(),
        server_default=sa.text("false"), nullable=False,
    ))
    op.add_column("channels", sa.Column("response_condensing_threshold", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_keep_exact", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_prompt", sa.Text(), nullable=True))

    # --- Channel: drop old summarizer columns ---
    op.drop_column("channels", "summarizer_enabled")
    op.drop_column("channels", "summarizer_threshold_minutes")
    op.drop_column("channels", "summarizer_message_count")
    op.drop_column("channels", "summarizer_target_size")
    op.drop_column("channels", "summarizer_prompt")
    op.drop_column("channels", "summarizer_model")


def downgrade() -> None:
    # Restore summarizer columns
    op.add_column("channels", sa.Column(
        "summarizer_enabled", sa.Boolean(),
        server_default=sa.text("false"), nullable=False,
    ))
    op.add_column("channels", sa.Column("summarizer_threshold_minutes", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_message_count", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_target_size", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_prompt", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_model", sa.String(), nullable=True))

    # Drop response_condensing columns
    op.drop_column("channels", "response_condensing_prompt")
    op.drop_column("channels", "response_condensing_model")
    op.drop_column("channels", "response_condensing_keep_exact")
    op.drop_column("channels", "response_condensing_threshold")
    op.drop_column("channels", "response_condensing_enabled")

    # Drop tags from conversation_sections
    op.drop_column("conversation_sections", "tags")

    # Drop condensed from messages
    op.drop_column("messages", "condensed")
