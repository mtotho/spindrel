"""Add ``grid_config`` JSONB to ``widget_dashboards``.

Per-dashboard layout preset so users can pick a coarser or finer grid
without affecting every dashboard globally. Shape:

    {"layout_type": "grid", "preset": "standard" | "fine"}

Existing rows get NULL, which the frontend treats as the ``standard``
preset — no data migration needed. When a user flips the preset on an
existing dashboard, the backend rescales every pin's ``grid_layout``
coords atomically (see ``app.services.dashboards.update_dashboard``).

Revision ID: 214
Revises: 213
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "214"
down_revision = "213"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_dashboards",
        sa.Column("grid_config", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("widget_dashboards", "grid_config")
