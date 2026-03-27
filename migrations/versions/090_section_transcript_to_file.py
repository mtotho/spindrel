"""Move section transcripts to filesystem.

Adds transcript_path column, drops transcript column.

Revision ID: 090
Revises: 089
"""
import sqlalchemy as sa
from alembic import op

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_sections", sa.Column("transcript_path", sa.Text(), nullable=True))
    op.drop_column("conversation_sections", "transcript")


def downgrade() -> None:
    op.add_column("conversation_sections", sa.Column("transcript", sa.Text(), nullable=False, server_default=sa.text("''")))
    op.drop_column("conversation_sections", "transcript_path")
