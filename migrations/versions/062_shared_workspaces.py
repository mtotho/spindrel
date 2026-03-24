"""Add shared_workspaces, shared_workspace_bots tables, and bots.user_id.

Revision ID: 062
Revises: 061
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shared_workspaces",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image", sa.Text(), nullable=False, server_default="python:3.12-slim"),
        sa.Column("network", sa.Text(), nullable=False, server_default="none"),
        sa.Column("env", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ports", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mounts", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cpus", sa.Float(), nullable=True),
        sa.Column("memory_limit", sa.Text(), nullable=True),
        sa.Column("docker_user", sa.Text(), nullable=True),
        sa.Column("read_only_root", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("container_id", sa.Text(), nullable=True),
        sa.Column("container_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="stopped"),
        sa.Column("image_id", sa.Text(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "shared_workspace_bots",
        sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("shared_workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_id", sa.Text(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="member"),
        sa.Column("cwd_override", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "bot_id"),
        sa.UniqueConstraint("bot_id"),
    )

    op.add_column("bots", sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "user_id")
    op.drop_table("shared_workspace_bots")
    op.drop_table("shared_workspaces")
