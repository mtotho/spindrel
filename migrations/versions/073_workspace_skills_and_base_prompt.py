"""Add workspace_skills_enabled and workspace_base_prompt_enabled to shared_workspaces and channels

Revision ID: 073
Revises: 072
"""
from alembic import op
import sqlalchemy as sa

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shared_workspaces",
        sa.Column("workspace_skills_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "shared_workspaces",
        sa.Column("workspace_base_prompt_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "channels",
        sa.Column("workspace_skills_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "channels",
        sa.Column("workspace_base_prompt_enabled", sa.Boolean(), nullable=True),
    )


def downgrade():
    op.drop_column("channels", "workspace_base_prompt_enabled")
    op.drop_column("channels", "workspace_skills_enabled")
    op.drop_column("shared_workspaces", "workspace_base_prompt_enabled")
    op.drop_column("shared_workspaces", "workspace_skills_enabled")
