"""Add summarizer and compression_prompt columns to channels

Revision ID: 076
Revises: 075
"""
from alembic import op
import sqlalchemy as sa

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade():
    # Summarizer (auto-resume after idle)
    op.add_column("channels", sa.Column("summarizer_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("channels", sa.Column("summarizer_threshold_minutes", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_message_count", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_target_size", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_prompt", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("summarizer_model", sa.String(), nullable=True))
    # Context compression prompt (per-channel override of hardcoded default)
    op.add_column("channels", sa.Column("compression_prompt", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("channels", "compression_prompt")
    op.drop_column("channels", "summarizer_model")
    op.drop_column("channels", "summarizer_prompt")
    op.drop_column("channels", "summarizer_target_size")
    op.drop_column("channels", "summarizer_message_count")
    op.drop_column("channels", "summarizer_threshold_minutes")
    op.drop_column("channels", "summarizer_enabled")
