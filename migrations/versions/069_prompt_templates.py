"""prompt_templates table

Revision ID: 069
Revises: 068
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("tags", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("shared_workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_prompt_templates_workspace_id", "prompt_templates", ["workspace_id"])
    op.create_index("ix_prompt_templates_category", "prompt_templates", ["category"])


def downgrade() -> None:
    op.drop_index("ix_prompt_templates_category")
    op.drop_index("ix_prompt_templates_workspace_id")
    op.drop_table("prompt_templates")
