"""Add widget_themes table for HTML widget SDK themes.

Revision ID: 235
Revises: 234
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "235"
down_revision = "234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_themes",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("forked_from_ref", sa.Text(), nullable=True),
        sa.Column("light_tokens", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dark_tokens", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("custom_css", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("widget_themes")
