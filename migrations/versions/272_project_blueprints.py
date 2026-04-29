"""project blueprints

Revision ID: 272_project_blueprints
Revises: 271_widget_health
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "272_project_blueprints"
down_revision = "271_widget_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_blueprints",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_root_path_pattern", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("prompt_file_path", sa.Text(), nullable=True),
        sa.Column("folders", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("knowledge_files", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("repos", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("env", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("required_secrets", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["shared_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_project_blueprints_workspace_slug"),
    )
    op.create_index("ix_project_blueprints_workspace_id", "project_blueprints", ["workspace_id"])
    op.add_column("projects", sa.Column("applied_blueprint_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_projects_applied_blueprint_id", "projects", ["applied_blueprint_id"])
    op.create_foreign_key(
        "fk_projects_applied_blueprint_id_project_blueprints",
        "projects",
        "project_blueprints",
        ["applied_blueprint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "project_secret_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_name", sa.Text(), nullable=False),
        sa.Column("secret_value_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secret_value_id"], ["secret_values.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "logical_name", name="uq_project_secret_bindings_project_name"),
    )
    op.create_index("ix_project_secret_bindings_project_id", "project_secret_bindings", ["project_id"])
    op.create_index("ix_project_secret_bindings_secret_value_id", "project_secret_bindings", ["secret_value_id"])


def downgrade() -> None:
    op.drop_index("ix_project_secret_bindings_secret_value_id", table_name="project_secret_bindings")
    op.drop_index("ix_project_secret_bindings_project_id", table_name="project_secret_bindings")
    op.drop_table("project_secret_bindings")
    op.drop_constraint("fk_projects_applied_blueprint_id_project_blueprints", "projects", type_="foreignkey")
    op.drop_index("ix_projects_applied_blueprint_id", table_name="projects")
    op.drop_column("projects", "applied_blueprint_id")
    op.drop_index("ix_project_blueprints_workspace_id", table_name="project_blueprints")
    op.drop_table("project_blueprints")
