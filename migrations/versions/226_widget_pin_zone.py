"""Add ``widget_dashboard_pins.zone`` enum column + one-shot backfill.

Chat-zone membership was previously *computed* per-pin by
``app.services.channel_chat_zones.classify_pin`` against the dashboard's
``grid_config.preset`` and the pin's ``grid_layout.x/y/h``. The rule was
invisible to the authoring UI — users couldn't predict which chat surface a
widget would land on. This migration replaces the positional classifier with
an explicit ``zone`` column (``rail | header | dock | grid``) and rewrites
every existing channel pin's ``grid_layout`` to be *canvas-local* (Rail/Dock
are 1-column; Header is 1-row).

Backfill inlines the *current* classifier rules one last time so cutover is
behavior-preserving for rows the UI already surfaced correctly. After this
migration the runtime classifier is deleted and zone is authored directly on
the dashboard via the multi-canvas editor.

Revision ID: 226
Revises: 225
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "226"
down_revision = "225"
branch_labels = None
depends_on = None


# Mirror of app/services/grid_presets.py at this migration's cut date. Inlined
# so future refactors of the runtime presets don't accidentally rewrite
# history. Values: (cols_lg, rail_zone_cols, dock_right_cols).
_PRESET_FIELDS: dict[str, tuple[int, int, int]] = {
    "standard": (12, 3, 3),
    "fine": (24, 6, 6),
}
_DEFAULT_PRESET = "standard"


def _resolve_preset(grid_config) -> tuple[int, int, int]:
    """Pick preset fields from a dashboard's ``grid_config`` JSON dict."""
    if isinstance(grid_config, dict):
        pid = grid_config.get("preset")
        if pid in _PRESET_FIELDS:
            return _PRESET_FIELDS[pid]
    return _PRESET_FIELDS[_DEFAULT_PRESET]


def _classify(gl: dict, cols_lg: int, rail_cols: int, dock_cols: int) -> str:
    """Replica of ``channel_chat_zones.classify_pin`` at this point in time."""
    if not isinstance(gl, dict):
        return "grid"
    x = gl.get("x")
    y = gl.get("y")
    h = gl.get("h")
    if not isinstance(x, int):
        return "grid"
    if x < rail_cols:
        return "rail"
    if x >= cols_lg - dock_cols:
        return "dock_right"
    if isinstance(y, int) and isinstance(h, int) and y == 0 and h == 1:
        return "header_chip"
    return "grid"


def upgrade() -> None:
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "zone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'grid'"),
        ),
    )

    bind = op.get_bind()
    dialect = bind.dialect.name

    # Pull every pin + its dashboard's grid_config. JSONB on Postgres, JSON on
    # SQLite — both return parsed dicts via SQLAlchemy Core.
    rows = bind.execute(sa.text("""
        SELECT p.id, p.dashboard_key, p.grid_layout, p.position, d.grid_config
          FROM widget_dashboard_pins p
          JOIN widget_dashboards d ON d.slug = p.dashboard_key
         WHERE p.dashboard_key LIKE 'channel:%'
    """)).all()

    header_position_counters: dict[str, int] = {}

    for row in rows:
        pin_id = row.id
        dashboard_key = row.dashboard_key
        gl_raw = row.grid_layout
        grid_config_raw = row.grid_config

        # SQLite returns JSON as strings; Postgres returns dicts. Normalize.
        gl = gl_raw if isinstance(gl_raw, dict) else (json.loads(gl_raw) if gl_raw else {})
        grid_config = (
            grid_config_raw if isinstance(grid_config_raw, dict)
            else (json.loads(grid_config_raw) if grid_config_raw else None)
        )

        cols_lg, rail_cols, dock_cols = _resolve_preset(grid_config)
        zone_legacy = _classify(gl, cols_lg, rail_cols, dock_cols)

        # Map the legacy bucket names to the new compact zone names and
        # rewrite coords to be canvas-local.
        if zone_legacy == "rail":
            zone = "rail"
            new_gl = {
                "x": 0,
                "y": gl.get("y", 0) if isinstance(gl.get("y"), int) else 0,
                "w": 1,
                "h": max(2, gl.get("h", 6)) if isinstance(gl.get("h"), int) else 6,
            }
        elif zone_legacy == "dock_right":
            zone = "dock"
            new_gl = {
                "x": 0,
                "y": gl.get("y", 0) if isinstance(gl.get("y"), int) else 0,
                "w": 1,
                "h": max(2, gl.get("h", 6)) if isinstance(gl.get("h"), int) else 6,
            }
        elif zone_legacy == "header_chip":
            zone = "header"
            idx = header_position_counters.get(dashboard_key, 0)
            header_position_counters[dashboard_key] = idx + 1
            new_gl = {"x": idx, "y": 0, "w": 1, "h": 1}
        else:
            zone = "grid"
            new_gl = gl  # keep as-is

        # Persist. JSON payload is dialect-agnostic via parameter binding.
        bind.execute(
            sa.text(
                "UPDATE widget_dashboard_pins "
                "SET zone = :zone, grid_layout = :gl "
                "WHERE id = :id"
            ),
            {"zone": zone, "gl": json.dumps(new_gl), "id": pin_id},
        )

    # Non-channel dashboard pins keep the server-default 'grid'. Nothing to do.

    # Drop the server default now that every row has an explicit value; the
    # ORM supplies ``default='grid'`` going forward.
    if dialect == "postgresql":
        op.alter_column(
            "widget_dashboard_pins",
            "zone",
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("widget_dashboard_pins", "zone")
