"""workspace spatial landmarks

Revision ID: 263_spatial_landmarks
Revises: 262_tool_call_error_kind
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "263_spatial_landmarks"
down_revision = "262_tool_call_error_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent because the original over-long revision id failed while
    # recording alembic_version on startup in some environments.
    op.execute(
        "ALTER TABLE workspace_spatial_nodes "
        "ADD COLUMN IF NOT EXISTS landmark_kind TEXT"
    )
    op.execute(
        "ALTER TABLE workspace_spatial_nodes "
        "DROP CONSTRAINT IF EXISTS ck_workspace_spatial_nodes_target_exactly_one"
    )
    op.create_check_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        "((CASE WHEN channel_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN landmark_kind IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_spatial_nodes_landmark_kind "
        "ON workspace_spatial_nodes (landmark_kind) "
        "WHERE landmark_kind IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workspace_spatial_nodes_landmark_kind")
    op.execute(
        "ALTER TABLE workspace_spatial_nodes "
        "DROP CONSTRAINT IF EXISTS ck_workspace_spatial_nodes_target_exactly_one"
    )
    op.create_check_constraint(
        "ck_workspace_spatial_nodes_target_exactly_one",
        "workspace_spatial_nodes",
        "((CASE WHEN channel_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN widget_pin_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN bot_id IS NOT NULL THEN 1 ELSE 0 END)) = 1",
    )
    op.execute(
        "ALTER TABLE workspace_spatial_nodes DROP COLUMN IF EXISTS landmark_kind"
    )
