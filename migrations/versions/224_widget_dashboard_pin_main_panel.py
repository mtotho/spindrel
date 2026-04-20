"""Add ``widget_dashboard_pins.is_main_panel`` flag for panel-mode dashboards.

When a dashboard's ``grid_config.layout_mode`` is ``"panel"``, exactly one of
its pins carries ``is_main_panel=TRUE`` and renders in the main area; the
remaining pins (typically rail-zone) keep their normal grid coordinates and
surface in the rail strip alongside the main panel.

A partial unique index enforces "at most one panel pin per dashboard". SQLite
in-memory tests skip partial-index enforcement; the service layer
(``app/services/dashboard_pins.py::promote_pin_to_panel``) does an atomic
clear-then-set so tests still observe the constraint.

Revision ID: 224
Revises: 223
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "224"
down_revision = "223"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "is_main_panel",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_index(
        "uq_widget_dashboard_pins_main_panel",
        "widget_dashboard_pins",
        ["dashboard_key"],
        unique=True,
        postgresql_where=sa.text("is_main_panel = TRUE"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_widget_dashboard_pins_main_panel",
        table_name="widget_dashboard_pins",
    )
    op.drop_column("widget_dashboard_pins", "is_main_panel")
