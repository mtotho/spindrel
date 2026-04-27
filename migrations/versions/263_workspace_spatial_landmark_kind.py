"""workspace spatial landmark_kind

Revision ID: 263_workspace_spatial_landmark_kind
Revises: 262_tool_call_error_kind
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "263_workspace_spatial_landmark_kind"
down_revision = "262_tool_call_error_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_spatial_nodes",
        sa.Column("landmark_kind", sa.Text(), nullable=True),
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
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN landmark_kind IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.create_index(
        "uq_workspace_spatial_nodes_landmark_kind",
        "workspace_spatial_nodes",
        ["landmark_kind"],
        unique=True,
        postgresql_where=sa.text("landmark_kind IS NOT NULL"),
        sqlite_where=sa.text("landmark_kind IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workspace_spatial_nodes_landmark_kind",
        table_name="workspace_spatial_nodes",
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
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.drop_column("workspace_spatial_nodes", "landmark_kind")
