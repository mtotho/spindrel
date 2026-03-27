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

    # Default history_mode for new bots: summary -> file
    op.alter_column("bots", "history_mode", server_default=sa.text("'file'"))
    op.execute("UPDATE bots SET history_mode = 'file' WHERE history_mode = 'summary' OR history_mode IS NULL")


def downgrade() -> None:
    op.add_column("conversation_sections", sa.Column("transcript", sa.Text(), nullable=False, server_default=sa.text("''")))
    op.drop_column("conversation_sections", "transcript_path")

    op.alter_column("bots", "history_mode", server_default=sa.text("'summary'"))
    op.execute("UPDATE bots SET history_mode = 'summary' WHERE history_mode = 'file'")
