"""spatial project nodes

Revision ID: 283_spatial_project_nodes
Revises: 282_issue_work_packs
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "283_spatial_project_nodes"
down_revision = "282_issue_work_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_spatial_nodes",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_workspace_spatial_nodes_project_id_projects",
        "workspace_spatial_nodes",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        "((CASE WHEN channel_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN project_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN landmark_kind IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.create_index(
        "uq_workspace_spatial_nodes_project",
        "workspace_spatial_nodes",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
        sqlite_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_spatial_nodes_project", table_name="workspace_spatial_nodes")
    op.drop_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        "((CASE WHEN channel_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN landmark_kind IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.drop_constraint(
        "fk_workspace_spatial_nodes_project_id_projects",
        "workspace_spatial_nodes",
        type_="foreignkey",
    )
    op.drop_column("workspace_spatial_nodes", "project_id")
