"""Backfill default ``grid_layout`` on existing channel dashboard pins.

Migration 213 moved ``channels.config.pinned_widgets`` rows into
``widget_dashboard_pins`` but wrote ``grid_layout={}`` for each one. The
frontend's rail-zone rule (``x < railZoneCols``) needs an actual ``x``
to decide whether a pin surfaces in the OmniPanel sidebar.

This one-shot assigns ``{x:0, y:position*6, w:6, h:6}`` to any
channel-dashboard pin whose ``grid_layout`` is missing or empty —
stacks them vertically at the leftmost column so they all land in the
rail zone. Pins already laid out on the grid are left untouched.

New pins created after this release get the same default for channel
dashboards via ``app.services.dashboard_pins._default_grid_layout(channel=True)``.

Revision ID: 215
Revises: 214
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID


revision = "215"
down_revision = "214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    pins = sa.table(
        "widget_dashboard_pins",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("dashboard_key", sa.Text()),
        sa.column("position", sa.Integer()),
        sa.column("grid_layout", JSONB()),
    )

    rows = conn.execute(
        sa.select(pins.c.id, pins.c.position, pins.c.grid_layout)
        .where(pins.c.dashboard_key.like("channel:%"))
        .order_by(pins.c.position)
    ).fetchall()

    for pid, position, gl in rows:
        # Skip pins already placed on the grid. "Already placed" = dict with
        # an x coordinate (JSON object vs. empty/null).
        if isinstance(gl, dict) and gl and "x" in gl:
            continue
        layout = {"x": 0, "y": int(position or 0) * 6, "w": 6, "h": 6}
        conn.execute(
            sa.update(pins).where(pins.c.id == pid).values(grid_layout=layout)
        )


def downgrade() -> None:
    """Best-effort reverse: re-empty the layouts we wrote.

    We can only identify our own writes heuristically (x=0, w=6, h=6, y a
    multiple of 6). Good enough for test parity — this migration is
    one-shot in production.
    """
    conn = op.get_bind()

    pins = sa.table(
        "widget_dashboard_pins",
        sa.column("id", PgUUID(as_uuid=True)),
        sa.column("dashboard_key", sa.Text()),
        sa.column("grid_layout", JSONB()),
    )

    rows = conn.execute(
        sa.select(pins.c.id, pins.c.grid_layout)
        .where(pins.c.dashboard_key.like("channel:%"))
    ).fetchall()

    for pid, gl in rows:
        if not isinstance(gl, dict):
            continue
        if gl.get("x") == 0 and gl.get("w") == 6 and gl.get("h") == 6:
            y = gl.get("y", 0)
            if isinstance(y, int) and y % 6 == 0:
                conn.execute(
                    sa.update(pins).where(pins.c.id == pid).values(grid_layout={})
                )
