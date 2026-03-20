"""Add client_id scope to filesystem_chunks; make bot_id nullable.

Revision ID: 027
Revises: 026
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make bot_id nullable (NULL = cross-bot, any bot can retrieve)
    op.alter_column("filesystem_chunks", "bot_id", nullable=True)
    # Add client_id for channel-level scoping (NULL = cross-client)
    op.add_column(
        "filesystem_chunks",
        sa.Column("client_id", sa.Text(), nullable=True),
    )
    # Index for scope-filtered retrieval
    op.create_index(
        "ix_filesystem_chunks_scope",
        "filesystem_chunks",
        ["bot_id", "client_id", "root"],
    )


def downgrade() -> None:
    op.drop_index("ix_filesystem_chunks_scope", "filesystem_chunks")
    op.drop_column("filesystem_chunks", "client_id")
    op.alter_column("filesystem_chunks", "bot_id", nullable=False)
