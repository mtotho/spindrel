"""Add integration_manifests table for declarative integration.yaml support.

Revision ID: 182
Revises: 181
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "182"
down_revision = "181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_manifests",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=False, server_default=sa.text("'Plug'")),
        sa.Column("manifest", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("yaml_content", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'yaml'")),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("integration_manifests")
