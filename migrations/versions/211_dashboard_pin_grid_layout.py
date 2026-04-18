"""Dashboard pin grid layout — {x, y, w, h} per pin for HA/Grafana-style grid.

Phase 5 of the Widget Dashboard + Developer Panel track. Adds a jsonb
``grid_layout`` column to ``widget_dashboard_pins`` carrying the ``{x, y, w, h}``
coordinates used by ``react-grid-layout`` on the frontend. Existing rows are
backfilled from ``position`` into a 12-column grid so the first load isn't
empty. The ``position`` column is retained as a fallback order for
layout-off/mobile rendering.

Revision ID: 211
Revises: 210
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "211"
down_revision = "210"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "grid_layout",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Backfill existing rows into a 12-col grid with 6x6 tiles.
    op.execute(
        """
        UPDATE widget_dashboard_pins
        SET grid_layout = jsonb_build_object(
            'x', (position % 2) * 6,
            'y', (position / 2) * 6,
            'w', 6,
            'h', 6
        )
        WHERE grid_layout = '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.drop_column("widget_dashboard_pins", "grid_layout")
