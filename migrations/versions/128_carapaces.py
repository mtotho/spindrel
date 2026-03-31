"""Add carapaces table and bot/channel carapace columns.

Revision ID: 128
Revises: 127
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "128"
down_revision = "127"


def upgrade() -> None:
    op.create_table(
        "carapaces",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("skills", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("local_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("mcp_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pinned_tools", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("system_prompt_fragment", sa.Text, nullable=True),
        sa.Column("includes", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("tags", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source_path", sa.Text, nullable=True),
        sa.Column("source_type", sa.Text, nullable=False, server_default=sa.text("'manual'")),
        sa.Column("content_hash", sa.Text, nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # Bot: add carapaces JSONB column
    op.add_column("bots", sa.Column("carapaces", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))

    # Channel: add carapaces_extra and carapaces_disabled
    op.add_column("channels", sa.Column("carapaces_extra", JSONB, nullable=True))
    op.add_column("channels", sa.Column("carapaces_disabled", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "carapaces_disabled")
    op.drop_column("channels", "carapaces_extra")
    op.drop_column("bots", "carapaces")
    op.drop_table("carapaces")
