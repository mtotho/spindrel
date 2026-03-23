"""Add bot-level attachment configuration columns.

Revision ID: 052
Revises: 051
"""
from alembic import op
import sqlalchemy as sa

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("attachment_summarization_enabled", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("attachment_summary_model", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("attachment_text_max_chars", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("attachment_vision_concurrency", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "attachment_vision_concurrency")
    op.drop_column("bots", "attachment_text_max_chars")
    op.drop_column("bots", "attachment_summary_model")
    op.drop_column("bots", "attachment_summarization_enabled")
