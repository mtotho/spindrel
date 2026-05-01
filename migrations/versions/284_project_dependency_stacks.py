"""project dependency stacks

Revision ID: 284_project_runtime_stacks
Revises: 283_spatial_project_nodes
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "284_project_runtime_stacks"
down_revision = "283_spatial_project_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_blueprints",
        sa.Column(
            "dependency_stack",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_table(
        "project_dependency_stack_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("docker_stack_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.Text(), server_default=sa.text("'task'"), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'not_prepared'"), nullable=False),
        sa.Column("env", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("commands", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("last_action", sa.Text(), nullable=True),
        sa.Column("last_result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("scope in ('project', 'task', 'project_instance')", name="ck_project_dependency_stack_instances_scope"),
        sa.CheckConstraint("status in ('not_prepared', 'preparing', 'running', 'stopped', 'failed', 'deleted')", name="ck_project_dependency_stack_instances_status"),
        sa.ForeignKeyConstraint(["docker_stack_id"], ["docker_stacks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_instance_id"], ["project_instances.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_dependency_stack_instances_docker_stack_id", "project_dependency_stack_instances", ["docker_stack_id"])
    op.create_index("ix_project_dependency_stack_instances_project_created", "project_dependency_stack_instances", ["project_id", "created_at"])
    op.create_index("ix_project_dependency_stack_instances_project_id", "project_dependency_stack_instances", ["project_id"])
    op.create_index("ix_project_dependency_stack_instances_project_instance_id", "project_dependency_stack_instances", ["project_instance_id"])
    op.create_index("ix_project_dependency_stack_instances_task_id", "project_dependency_stack_instances", ["task_id"])
    op.create_index(
        "uq_project_dependency_stack_instances_task",
        "project_dependency_stack_instances",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("task_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_project_dependency_stack_instances_project_shared",
        "project_dependency_stack_instances",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'project' AND deleted_at IS NULL"),
        sqlite_where=sa.text("scope = 'project' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_dependency_stack_instances_project_shared", table_name="project_dependency_stack_instances")
    op.drop_index("uq_project_dependency_stack_instances_task", table_name="project_dependency_stack_instances")
    op.drop_index("ix_project_dependency_stack_instances_task_id", table_name="project_dependency_stack_instances")
    op.drop_index("ix_project_dependency_stack_instances_project_instance_id", table_name="project_dependency_stack_instances")
    op.drop_index("ix_project_dependency_stack_instances_project_id", table_name="project_dependency_stack_instances")
    op.drop_index("ix_project_dependency_stack_instances_project_created", table_name="project_dependency_stack_instances")
    op.drop_index("ix_project_dependency_stack_instances_docker_stack_id", table_name="project_dependency_stack_instances")
    op.drop_table("project_dependency_stack_instances")
    op.drop_column("project_blueprints", "dependency_stack")
