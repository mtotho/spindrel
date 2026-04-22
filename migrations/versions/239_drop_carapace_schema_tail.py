"""drop remaining carapace schema tail

Revision ID: 239
Revises: 238
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


# revision identifiers, used by Alembic.
revision = "239"
down_revision = "238"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("channels", "carapaces_disabled")
    op.drop_column("channels", "carapaces_extra")
    op.drop_column("bots", "carapaces")
    op.execute("DROP INDEX IF EXISTS ix_capability_embeddings_hnsw")
    op.drop_table("capability_embeddings")
    op.drop_table("carapaces")


def downgrade() -> None:
    op.create_table(
        "carapaces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("local_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("mcp_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pinned_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("system_prompt_fragment", sa.Text(), nullable=True),
        sa.Column("includes", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("delegates", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tags", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("requires", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_table(
        "capability_embeddings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("carapace_id", sa.Text(), unique=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("indexed_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE INDEX ix_capability_embeddings_hnsw ON capability_embeddings "
        "USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.add_column("bots", sa.Column("carapaces", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("channels", sa.Column("carapaces_extra", JSONB, nullable=True))
    op.add_column("channels", sa.Column("carapaces_disabled", JSONB, nullable=True))
