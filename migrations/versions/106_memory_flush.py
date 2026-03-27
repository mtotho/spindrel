"""Add memory flush columns to channels.

Revision ID: 106
Revises: 105
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "106"
down_revision = "105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("memory_flush_enabled", sa.Boolean(), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_model_provider_id", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_prompt", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_prompt_template_id",
        UUID(as_uuid=True), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_workspace_file_path", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("memory_flush_workspace_id",
        UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_channels_memory_flush_prompt_template",
        "channels", "prompt_templates",
        ["memory_flush_prompt_template_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_channels_memory_flush_workspace",
        "channels", "shared_workspaces",
        ["memory_flush_workspace_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_channels_memory_flush_workspace", "channels", type_="foreignkey")
    op.drop_constraint("fk_channels_memory_flush_prompt_template", "channels", type_="foreignkey")
    op.drop_column("channels", "memory_flush_workspace_id")
    op.drop_column("channels", "memory_flush_workspace_file_path")
    op.drop_column("channels", "memory_flush_prompt_template_id")
    op.drop_column("channels", "memory_flush_prompt")
    op.drop_column("channels", "memory_flush_model_provider_id")
    op.drop_column("channels", "memory_flush_model")
    op.drop_column("channels", "memory_flush_enabled")
