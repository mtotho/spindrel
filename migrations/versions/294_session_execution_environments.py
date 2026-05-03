"""Add session execution environments.

Revision ID: 294_session_exec_envs
Revises: 293_drop_issue_work_packs
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "294_session_exec_envs"
down_revision = "293_drop_issue_work_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_execution_environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.Text(), server_default=sa.text("'shared'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'preparing'"), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("docker_endpoint", sa.Text(), nullable=True),
        sa.Column("docker_container_id", sa.Text(), nullable=True),
        sa.Column("docker_container_name", sa.Text(), nullable=True),
        sa.Column("docker_state_volume", sa.Text(), nullable=True),
        sa.Column("docker_status", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("mode in ('shared', 'isolated')", name="ck_session_execution_environments_mode"),
        sa.CheckConstraint("status in ('preparing', 'ready', 'stopped', 'failed', 'deleted')", name="ck_session_execution_environments_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_instance_id"], ["project_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_execution_environments_session_id", "session_execution_environments", ["session_id"])
    op.create_index("ix_session_execution_environments_project_id", "session_execution_environments", ["project_id"])
    op.create_index("ix_session_execution_environments_project_instance_id", "session_execution_environments", ["project_instance_id"])
    op.create_index("ix_session_execution_environments_expires_at", "session_execution_environments", ["expires_at"])
    op.create_index("ix_session_execution_environments_status_updated", "session_execution_environments", ["status", sa.text("updated_at DESC")])
    op.create_index(
        "uq_session_execution_environments_active_session",
        "session_execution_environments",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_session_execution_environments_active_session", table_name="session_execution_environments")
    op.drop_index("ix_session_execution_environments_status_updated", table_name="session_execution_environments")
    op.drop_index("ix_session_execution_environments_expires_at", table_name="session_execution_environments")
    op.drop_index("ix_session_execution_environments_project_instance_id", table_name="session_execution_environments")
    op.drop_index("ix_session_execution_environments_project_id", table_name="session_execution_environments")
    op.drop_index("ix_session_execution_environments_session_id", table_name="session_execution_environments")
    op.drop_table("session_execution_environments")
