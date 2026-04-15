"""Drop container-specific columns from shared_workspaces.

The workspace container has been collapsed into the server process.
Commands now run via subprocess instead of docker exec, so container
lifecycle columns are no longer needed.

Revision ID: 196
Revises: 195
"""
from alembic import op
import sqlalchemy as sa

revision = "196"
down_revision = "195"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("shared_workspaces", "container_id")
    op.drop_column("shared_workspaces", "container_name")
    op.drop_column("shared_workspaces", "status")
    op.drop_column("shared_workspaces", "image")
    op.drop_column("shared_workspaces", "image_id")
    op.drop_column("shared_workspaces", "network")
    op.drop_column("shared_workspaces", "ports")
    op.drop_column("shared_workspaces", "mounts")
    op.drop_column("shared_workspaces", "cpus")
    op.drop_column("shared_workspaces", "memory_limit")
    op.drop_column("shared_workspaces", "docker_user")
    op.drop_column("shared_workspaces", "read_only_root")
    op.drop_column("shared_workspaces", "startup_script")
    op.drop_column("shared_workspaces", "last_started_at")
    op.drop_column("shared_workspaces", "editor_enabled")
    op.drop_column("shared_workspaces", "editor_port")


def downgrade() -> None:
    op.add_column("shared_workspaces", sa.Column("container_id", sa.Text(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("container_name", sa.Text(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'stopped'")))
    op.add_column("shared_workspaces", sa.Column("image", sa.Text(), nullable=False, server_default=sa.text("'python:3.12-slim'")))
    op.add_column("shared_workspaces", sa.Column("image_id", sa.Text(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("network", sa.Text(), nullable=False, server_default=sa.text("'none'")))
    op.add_column("shared_workspaces", sa.Column("ports", sa.JSON(), server_default=sa.text("'[]'::jsonb")))
    op.add_column("shared_workspaces", sa.Column("mounts", sa.JSON(), server_default=sa.text("'[]'::jsonb")))
    op.add_column("shared_workspaces", sa.Column("cpus", sa.Float(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("memory_limit", sa.Text(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("docker_user", sa.Text(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("read_only_root", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("shared_workspaces", sa.Column("startup_script", sa.Text(), nullable=True, server_default=sa.text("'/workspace/startup.sh'")))
    op.add_column("shared_workspaces", sa.Column("last_started_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("shared_workspaces", sa.Column("editor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("shared_workspaces", sa.Column("editor_port", sa.Integer(), nullable=True))
