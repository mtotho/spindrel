"""Filesystem indexing table.

Revision ID: 012
Revises: 011
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "filesystem_chunks",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("root", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("metadata_", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "indexed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_fs_chunks_bot_root", "filesystem_chunks", ["bot_id", "root"])
    op.create_index(
        "ix_fs_chunks_file_path", "filesystem_chunks", ["bot_id", "root", "file_path"]
    )
    op.create_index("ix_fs_chunks_indexed_at", "filesystem_chunks", ["indexed_at"])


def downgrade() -> None:
    op.drop_index("ix_fs_chunks_indexed_at", table_name="filesystem_chunks")
    op.drop_index("ix_fs_chunks_file_path", table_name="filesystem_chunks")
    op.drop_index("ix_fs_chunks_bot_root", table_name="filesystem_chunks")
    op.drop_table("filesystem_chunks")
