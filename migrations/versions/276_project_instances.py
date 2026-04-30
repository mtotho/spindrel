"""project instances

Revision ID: 276_project_instances
Revises: 275_project_setup_commands
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "276_project_instances"
down_revision = "275_project_setup_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'preparing'"), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'blueprint_snapshot'"), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("setup_result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("owner_kind", sa.Text(), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("owner_kind is null or owner_kind in ('task', 'session', 'manual')", name="ck_project_instances_owner_kind"),
        sa.CheckConstraint("status in ('preparing', 'ready', 'failed', 'expired', 'deleted')", name="ck_project_instances_status"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["shared_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "root_path", name="uq_project_instances_workspace_root_path"),
    )
    op.create_index("ix_project_instances_project_id", "project_instances", ["project_id"])
    op.create_index("ix_project_instances_project_created", "project_instances", ["project_id", sa.text("created_at DESC")])
    op.create_index("ix_project_instances_status_expires", "project_instances", ["status", "expires_at"])
    op.create_index("ix_project_instances_workspace_id", "project_instances", ["workspace_id"])
    op.add_column("sessions", sa.Column("project_instance_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_sessions_project_instance_id", "sessions", ["project_instance_id"])
    op.create_foreign_key(
        "fk_sessions_project_instance_id_project_instances",
        "sessions",
        "project_instances",
        ["project_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("tasks", sa.Column("project_instance_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_tasks_project_instance_id", "tasks", ["project_instance_id"])
    op.create_foreign_key(
        "fk_tasks_project_instance_id_project_instances",
        "tasks",
        "project_instances",
        ["project_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_project_instance_id_project_instances", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_project_instance_id", table_name="tasks")
    op.drop_column("tasks", "project_instance_id")
    op.drop_constraint("fk_sessions_project_instance_id_project_instances", "sessions", type_="foreignkey")
    op.drop_index("ix_sessions_project_instance_id", table_name="sessions")
    op.drop_column("sessions", "project_instance_id")
    op.drop_index("ix_project_instances_workspace_id", table_name="project_instances")
    op.drop_index("ix_project_instances_status_expires", table_name="project_instances")
    op.drop_index("ix_project_instances_project_created", table_name="project_instances")
    op.drop_index("ix_project_instances_project_id", table_name="project_instances")
    op.drop_table("project_instances")
