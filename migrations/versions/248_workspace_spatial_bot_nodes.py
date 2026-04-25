"""Workspace Spatial Canvas bot nodes.

Revision ID: 248
Revises: 247
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "248"
down_revision = "247"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_spatial_nodes",
        sa.Column("bot_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "workspace_spatial_nodes",
        sa.Column("last_movement", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
    op.create_index(
        "uq_workspace_spatial_nodes_bot",
        "workspace_spatial_nodes",
        ["bot_id"],
        unique=True,
        postgresql_where=sa.text("bot_id IS NOT NULL"),
        sqlite_where=sa.text("bot_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workspace_spatial_nodes_bot",
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
        "(channel_id IS NULL) <> (widget_pin_id IS NULL)",
    )
    op.drop_column("workspace_spatial_nodes", "last_movement")
    op.drop_column("workspace_spatial_nodes", "bot_id")
