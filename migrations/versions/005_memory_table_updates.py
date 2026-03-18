"""Add bot_id to memories table and SET NULL on session delete (optional wipe via app).

Revision ID: 005
Revises: 004
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add bot_id with default for existing rows
    op.add_column(
        "memories",
        sa.Column("bot_id", sa.Text(), nullable=False, server_default=sa.text("'default'")),
    )
    op.alter_column("memories", "bot_id", server_default=None)
    # Allow keeping memories when session is deleted: nullable session_id + SET NULL
    op.alter_column(
        "memories",
        "session_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.drop_constraint("memories_session_id_fkey", "memories", type_="foreignkey")
    op.create_foreign_key(
        "memories_session_id_fkey",
        "memories",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("memories_session_id_fkey", "memories", type_="foreignkey")
    op.create_foreign_key(
        "memories_session_id_fkey",
        "memories",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Leave session_id nullable to avoid failing on rows that were SET NULL
    op.drop_column("memories", "bot_id")
