"""projects

Revision ID: 270_projects
Revises: 269_heartbeat_task_execution
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "270_projects"
down_revision = "269_heartbeat_task_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("prompt_file_path", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["shared_workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "root_path", name="uq_projects_workspace_root_path"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])
    op.add_column("channels", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_channels_project_id", "channels", ["project_id"])
    op.create_foreign_key(
        "fk_channels_project_id_projects",
        "channels",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        WITH legacy AS (
            SELECT
                c.id AS channel_id,
                COALESCE(NULLIF(c.config->>'project_workspace_id', '')::uuid, c.workspace_id) AS workspace_id,
                regexp_replace(trim(both '/' from c.config->>'project_path'), '/+', '/', 'g') AS root_path
            FROM channels c
            WHERE c.config ? 'project_path'
              AND NULLIF(trim(both '/' from c.config->>'project_path'), '') IS NOT NULL
              AND COALESCE(NULLIF(c.config->>'project_workspace_id', '')::uuid, c.workspace_id) IS NOT NULL
        ),
        inserted AS (
            INSERT INTO projects (workspace_id, name, slug, root_path)
            SELECT DISTINCT
                l.workspace_id,
                regexp_replace(split_part(l.root_path, '/', array_length(string_to_array(l.root_path, '/'), 1)), '[^A-Za-z0-9_. -]+', ' ', 'g') AS name,
                lower(regexp_replace(l.root_path, '[^A-Za-z0-9]+', '-', 'g')) || '-' || substr(md5(l.workspace_id::text || ':' || l.root_path), 1, 8) AS slug,
                l.root_path
            FROM legacy l
            ON CONFLICT (workspace_id, root_path) DO NOTHING
            RETURNING id, workspace_id, root_path
        )
        UPDATE channels c
        SET project_id = p.id
        FROM legacy l
        JOIN projects p ON p.workspace_id = l.workspace_id AND p.root_path = l.root_path
        WHERE c.id = l.channel_id
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_channels_project_id_projects", "channels", type_="foreignkey")
    op.drop_index("ix_channels_project_id", table_name="channels")
    op.drop_column("channels", "project_id")
    op.drop_index("ix_projects_workspace_id", table_name="projects")
    op.drop_table("projects")
