"""Workspace Spatial Canvas — node placements.

P1 of the Spatial Canvas track. Creates ``workspace_spatial_nodes`` — the
single source of truth for tile positions on the workspace-scope canvas.
Seeds a reserved ``workspace:spatial`` row in ``widget_dashboards`` so the
existing widget-pin host plumbing can be reused for world-pinned widgets
(no second host path).

The ``workspace:spatial`` slug is reserved: every dashboard-listing surface
must filter it out (see ``app/services/dashboards.py::WORKSPACE_SPATIAL_DASHBOARD_KEY``).

Node target is polymorphic via two nullable FKs (``channel_id`` /
``widget_pin_id``) with a CHECK constraint that exactly one is set, plus
ON DELETE CASCADE on each so cleaning up a channel or a dashboard pin
removes its spatial node automatically.

Revision ID: 247
Revises: 246
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "247"
down_revision = "246"
branch_labels = None
depends_on = None


WORKSPACE_SPATIAL_DASHBOARD_KEY = "workspace:spatial"


def upgrade() -> None:
    # 1. Seed the reserved dashboard row that hosts world widget pins.
    op.execute(
        f"""
        INSERT INTO widget_dashboards (slug, name, icon)
        VALUES ('{WORKSPACE_SPATIAL_DASHBOARD_KEY}', 'Spatial Canvas', 'Map')
        ON CONFLICT (slug) DO NOTHING
        """
    )

    # 2. workspace_spatial_nodes table.
    op.create_table(
        "workspace_spatial_nodes",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("channel_id", UUID(as_uuid=True), nullable=True),
        sa.Column("widget_pin_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "world_x", sa.Float(), nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "world_y", sa.Float(), nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "world_w", sa.Float(), nullable=False, server_default=sa.text("220"),
        ),
        sa.Column(
            "world_h", sa.Float(), nullable=False, server_default=sa.text("140"),
        ),
        sa.Column(
            "z_index", sa.Integer(), nullable=False, server_default=sa.text("0"),
        ),
        sa.Column("seed_index", sa.Integer(), nullable=True),
        sa.Column(
            "pinned_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["channels.id"],
            name="fk_workspace_spatial_nodes_channel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["widget_pin_id"], ["widget_dashboard_pins.id"],
            name="fk_workspace_spatial_nodes_widget_pin",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(channel_id IS NULL) <> (widget_pin_id IS NULL)",
            name="ck_workspace_spatial_nodes_target_exactly_one",
        ),
    )

    # Partial unique indexes — one node per target. Honored on Postgres and
    # SQLite ≥3.8.
    op.create_index(
        "uq_workspace_spatial_nodes_channel",
        "workspace_spatial_nodes",
        ["channel_id"],
        unique=True,
        postgresql_where=sa.text("channel_id IS NOT NULL"),
        sqlite_where=sa.text("channel_id IS NOT NULL"),
    )
    op.create_index(
        "uq_workspace_spatial_nodes_widget_pin",
        "workspace_spatial_nodes",
        ["widget_pin_id"],
        unique=True,
        postgresql_where=sa.text("widget_pin_id IS NOT NULL"),
        sqlite_where=sa.text("widget_pin_id IS NOT NULL"),
    )
    op.create_index(
        "ix_workspace_spatial_nodes_seed_index",
        "workspace_spatial_nodes",
        ["seed_index"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_spatial_nodes_seed_index",
        table_name="workspace_spatial_nodes",
    )
    op.drop_index(
        "uq_workspace_spatial_nodes_widget_pin",
        table_name="workspace_spatial_nodes",
    )
    op.drop_index(
        "uq_workspace_spatial_nodes_channel",
        table_name="workspace_spatial_nodes",
    )
    op.drop_table("workspace_spatial_nodes")
    op.execute(
        f"DELETE FROM widget_dashboards WHERE slug = '{WORKSPACE_SPATIAL_DASHBOARD_KEY}'"
    )
