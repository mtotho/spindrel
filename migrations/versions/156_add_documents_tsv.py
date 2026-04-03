"""Add tsv TSVECTOR column + GIN index to documents table for BM25 hybrid search.

Revision ID: 156
Revises: 155
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "156"
down_revision = "155"


def upgrade() -> None:
    op.add_column("documents", sa.Column("tsv", TSVECTOR(), nullable=True))
    op.create_index("ix_documents_tsv", "documents", ["tsv"], postgresql_using="gin")
    # Backfill existing rows
    op.execute(
        "UPDATE documents SET tsv = to_tsvector('english', content) WHERE tsv IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_documents_tsv", table_name="documents")
    op.drop_column("documents", "tsv")
