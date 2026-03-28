"""Add memory_scheme to bots, tsv tsvector to filesystem_chunks.

Revision ID: 108
Revises: 107
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # memory_scheme column on bots
    op.add_column("bots", sa.Column("memory_scheme", sa.Text(), nullable=True))

    # tsvector column on filesystem_chunks for hybrid BM25 search
    op.add_column("filesystem_chunks", sa.Column("tsv", TSVECTOR, nullable=True))
    op.create_index(
        "ix_filesystem_chunks_tsv",
        "filesystem_chunks",
        ["tsv"],
        postgresql_using="gin",
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_filesystem_chunks_tsv", table_name="filesystem_chunks")
    op.drop_column("filesystem_chunks", "tsv")
    op.drop_column("bots", "memory_scheme")
