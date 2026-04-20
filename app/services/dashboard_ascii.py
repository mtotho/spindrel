"""ASCII-art rendering + free-slot helpers for widget dashboards.

Used by the bot-facing ``describe_dashboard`` / ``pin_widget`` / ``move_pins``
tools so agents can:

  - *See* the dashboard layout in-context (instead of guessing).
  - *Propose* a layout with an ASCII mockup ("here's what I'm thinking").
  - *Place* a new pin at a sensible empty slot without colliding.

The module is pure (no I/O, no DB). All inputs are plain dicts — typically
from ``dashboard_pins.serialize_pin`` — so this code stays easy to unit-test
and reusable from any caller that has pin rows in memory.

Two conceptual views:

  - **chat view** — what the user sees alongside a live chat: header strip
    across the top, rail on the left, dock on the right, with a labelled
    "[ chat column ]" placeholder in the middle so the agent understands
    *where* the chat sits spatially relative to the widgets.
  - **full view** — what the user sees on ``/widgets/channel/<uuid>``: the
    same layout, but the middle column is the actual grid zone rendered at
    the dashboard's preset col count with every pin's ``{x, y, w, h}``
    honoured.

Zones:

  - ``rail``   — 1-col canvas on the left (pin x=0, varies in y/h).
  - ``header`` — horizontal strip across the top (y=0, h=1, varies in x/w).
  - ``dock``   — 1-col canvas on the right.
  - ``grid``   — main 2D grid at the preset col count (12 or 24).
"""
from __future__ import annotations

from typing import Any, Iterable, Literal

ChatZone = Literal["rail", "header", "dock", "grid"]

# Ordered alphabet for pin labels. A..Z, then a..z = 52 unique tokens. If a
# dashboard has more than 52 pins, later entries fall back to ``??``.
_LABEL_ALPHABET = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
)

# Preset → (cols, rail_cols, dock_cols, max_visible_rows)
# Rail/dock are visually 1-col canvases; the rail_zone_cols / dock_right_cols
# in migration 226's legacy classifier referred to *chat-screen* widths, not
# the per-zone canvas. For ASCII rendering each of rail/dock is rendered as
# a single column.
_PRESETS: dict[str, dict[str, int]] = {
    "standard": {"cols": 12, "max_rows": 18, "header_cols": 12},
    "fine": {"cols": 24, "max_rows": 24, "header_cols": 24},
}
_DEFAULT_PRESET = "standard"

_EMPTY_CELL = "·"
_BAR = "═"


def _resolve_preset_name(grid_config: dict | None) -> str:
    if not isinstance(grid_config, dict):
        return _DEFAULT_PRESET
    preset = grid_config.get("preset")
    if preset in _PRESETS:
        return preset
    return _DEFAULT_PRESET


def _pin_coords(pin: dict[str, Any]) -> dict[str, int]:
    """Extract ``{x, y, w, h}`` with sensible defaults."""
    gl = pin.get("grid_layout") or {}
    if not isinstance(gl, dict):
        gl = {}
    return {
        "x": int(gl.get("x", 0) or 0),
        "y": int(gl.get("y", 0) or 0),
        "w": int(gl.get("w", 1) or 1),
        "h": int(gl.get("h", 1) or 1),
    }


def _pin_zone(pin: dict[str, Any]) -> ChatZone:
    zone = pin.get("zone") or "grid"
    if zone not in ("rail", "header", "dock", "grid"):
        return "grid"
    return zone  # type: ignore[return-value]


def _assign_labels(pins: list[dict[str, Any]]) -> dict[str, str]:
    """Return ``{pin_id: label}`` in pin order."""
    out: dict[str, str] = {}
    for i, pin in enumerate(pins):
        pid = str(pin.get("id"))
        out[pid] = _LABEL_ALPHABET[i] if i < len(_LABEL_ALPHABET) else "??"
    return out


def _group_by_zone(
    pins: list[dict[str, Any]],
) -> dict[ChatZone, list[dict[str, Any]]]:
    buckets: dict[ChatZone, list[dict[str, Any]]] = {
        "rail": [], "header": [], "dock": [], "grid": [],
    }
    for pin in pins:
        buckets[_pin_zone(pin)].append(pin)
    return buckets


def _occupancy(
    pins: Iterable[dict[str, Any]],
    *,
    cols: int,
    rows: int,
    labels: dict[str, str] | None = None,
) -> list[list[str]]:
    """Fill a ``rows x cols`` grid with labels where pins occupy cells.

    Out-of-range cells (pin extends past the grid bounds) are clipped. The
    rightmost / bottommost occupied cells win on overlap — deterministic for
    visual output, collision detection is a separate concern.
    """
    grid = [[_EMPTY_CELL for _ in range(cols)] for _ in range(rows)]
    for pin in pins:
        pid = str(pin.get("id"))
        label = (labels or {}).get(pid, "?")
        c = _pin_coords(pin)
        for dy in range(c["h"]):
            y = c["y"] + dy
            if y < 0 or y >= rows:
                continue
            for dx in range(c["w"]):
                x = c["x"] + dx
                if x < 0 or x >= cols:
                    continue
                grid[y][x] = label
    return grid


def _row_to_str(row: list[str], *, cell_width: int = 2) -> str:
    """Join a row of cells with uniform width so the ASCII grid aligns."""
    parts: list[str] = []
    for cell in row:
        parts.append(cell.ljust(cell_width))
    return " ".join(parts)


def _zone_height(pins: list[dict[str, Any]], *, fallback: int, cap: int) -> int:
    """Compute the minimum row count needed to show every pin in a 1-col zone."""
    max_y = 0
    for pin in pins:
        c = _pin_coords(pin)
        max_y = max(max_y, c["y"] + c["h"])
    return min(cap, max(fallback, max_y))


def _render_header_strip(
    header_pins: list[dict[str, Any]],
    labels: dict[str, str],
    *,
    cols: int,
) -> list[str]:
    """Render the header zone as a single row of ``cols`` cells."""
    grid = _occupancy(header_pins, cols=cols, rows=1, labels=labels)
    line = _row_to_str(grid[0])
    width = len(line)
    bar = _BAR * (width + 2)
    title = " header "
    title_line = title.center(width + 2, _BAR)
    return [
        f"┌{title_line}┐",
        f"│ {line} │",
        f"└{bar}┘",
    ]


def _render_middle_row(
    rail_pins: list[dict[str, Any]],
    dock_pins: list[dict[str, Any]],
    labels: dict[str, str],
    *,
    middle_label: str,
    middle_width: int,
    rows: int,
) -> list[str]:
    """Render rail | middle | dock as aligned columns."""
    rail_grid = _occupancy(rail_pins, cols=1, rows=rows, labels=labels)
    dock_grid = _occupancy(dock_pins, cols=1, rows=rows, labels=labels)

    rail_col_width = 2  # one cell, fixed width
    dock_col_width = 2

    header_line = (
        f"┌ rail ┬{(' ' + middle_label + ' ').center(middle_width + 2, '─')}┬ dock ┐"
    )
    out: list[str] = [header_line]
    for i in range(rows):
        rail_cell = rail_grid[i][0].ljust(rail_col_width)
        dock_cell = dock_grid[i][0].ljust(dock_col_width)
        middle = " " * middle_width
        out.append(f"│ {rail_cell}   │ {middle} │ {dock_cell}   │")
    footer = (
        f"└──────┴{'─' * (middle_width + 2)}┴──────┘"
    )
    out.append(footer)
    return out


def _render_middle_grid_row(
    rail_pins: list[dict[str, Any]],
    dock_pins: list[dict[str, Any]],
    grid_pins: list[dict[str, Any]],
    labels: dict[str, str],
    *,
    cols: int,
    rows: int,
) -> list[str]:
    """Render rail | grid-matrix | dock."""
    rail_grid = _occupancy(rail_pins, cols=1, rows=rows, labels=labels)
    dock_grid = _occupancy(dock_pins, cols=1, rows=rows, labels=labels)
    grid_grid = _occupancy(grid_pins, cols=cols, rows=rows, labels=labels)

    middle_width = len(_row_to_str(grid_grid[0])) if rows > 0 else cols * 3

    header_line = (
        f"┌ rail ┬{(' grid ').center(middle_width + 2, '─')}┬ dock ┐"
    )
    out: list[str] = [header_line]
    for i in range(rows):
        rail_cell = rail_grid[i][0].ljust(2)
        dock_cell = dock_grid[i][0].ljust(2)
        middle = _row_to_str(grid_grid[i])
        # Pad middle to middle_width in case of trailing truncation.
        out.append(f"│ {rail_cell}   │ {middle} │ {dock_cell}   │")
    footer = (
        f"└──────┴{'─' * (middle_width + 2)}┴──────┘"
    )
    out.append(footer)
    return out


def render_legend(
    pins: list[dict[str, Any]], labels: dict[str, str],
) -> list[str]:
    """Build a human-readable legend for every labelled pin."""
    if not pins:
        return ["(no pins yet — the dashboard is empty)"]
    out: list[str] = ["Legend:"]
    for pin in pins:
        pid = str(pin.get("id"))
        label = labels.get(pid, "?")
        zone = _pin_zone(pin)
        c = _pin_coords(pin)
        display = pin.get("display_label") or pin.get("tool_name") or "<widget>"
        panel_tag = " [panel]" if pin.get("is_main_panel") else ""
        tid = pid[:8]
        out.append(
            f"  {label} = {display} ({zone}, {c['w']}×{c['h']} at "
            f"x={c['x']},y={c['y']}){panel_tag} [pin {tid}…]"
        )
    return out


def render_layout(
    dashboard: dict[str, Any] | None,
    pins: list[dict[str, Any]],
    *,
    view: Literal["chat", "full", "both"] = "both",
) -> str:
    """Render an ASCII picture of the dashboard.

    Returns a multi-line string. For ``view="both"`` the chat view renders
    first, then the full dashboard view, with a blank line between.
    """
    grid_config = (dashboard or {}).get("grid_config")
    preset_name = _resolve_preset_name(grid_config)
    preset = _PRESETS[preset_name]

    labels = _assign_labels(pins)
    buckets = _group_by_zone(pins)

    header_cols = preset["header_cols"]
    grid_cols = preset["cols"]

    rows_for_rail_dock = _zone_height(
        buckets["rail"] + buckets["dock"], fallback=4, cap=preset["max_rows"],
    )
    rows_for_grid = _zone_height(
        buckets["grid"], fallback=max(rows_for_rail_dock, 6), cap=preset["max_rows"],
    )

    blocks: list[list[str]] = []

    if view in ("chat", "both"):
        chat_title = f"CHAT VIEW — what the user sees while chatting "
        chat_title += f"(preset={preset_name})"
        block = [chat_title, "─" * len(chat_title)]
        block.extend(_render_header_strip(buckets["header"], labels, cols=header_cols))
        # Middle row width: match the grid row width so chat view and full view
        # visually line up. grid row width = cols * 3 - 1 (two chars + one space).
        middle_width = grid_cols * 3 - 1
        block.extend(_render_middle_row(
            buckets["rail"], buckets["dock"], labels,
            middle_label="[ chat column ]",
            middle_width=middle_width,
            rows=rows_for_rail_dock,
        ))
        blocks.append(block)

    if view in ("full", "both"):
        full_title = f"FULL DASHBOARD VIEW — /widgets/channel/<uuid> "
        full_title += f"(preset={preset_name}, {grid_cols} cols)"
        block = [full_title, "─" * len(full_title)]
        block.extend(_render_header_strip(buckets["header"], labels, cols=header_cols))
        block.extend(_render_middle_grid_row(
            buckets["rail"], buckets["dock"], buckets["grid"], labels,
            cols=grid_cols,
            rows=rows_for_grid,
        ))
        blocks.append(block)

    # Legend goes at the bottom, shared across both views.
    legend = render_legend(pins, labels)

    # Panel-mode hint.
    panel_pins = [p for p in pins if p.get("is_main_panel")]
    extras: list[str] = []
    if panel_pins:
        p = panel_pins[0]
        pid = str(p.get("id"))[:8]
        label = p.get("display_label") or p.get("tool_name") or "<widget>"
        extras.append(
            f"Panel mode: {label!r} is promoted as the dashboard's main panel "
            f"(pin {pid}…). The grid matrix is suppressed in favour of this pin "
            f"on /widgets/channel/<uuid>."
        )

    sections: list[str] = []
    for block in blocks:
        sections.append("\n".join(block))
    sections.append("\n".join(legend))
    if extras:
        sections.append("\n".join(extras))
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# First-free-slot finder
# ---------------------------------------------------------------------------


def _zone_cols(zone: ChatZone, preset_name: str) -> int:
    preset = _PRESETS.get(preset_name, _PRESETS[_DEFAULT_PRESET])
    if zone == "rail" or zone == "dock":
        return 1
    if zone == "header":
        return preset["header_cols"]
    return preset["cols"]


def _zone_max_rows(zone: ChatZone, preset_name: str) -> int:
    """Soft cap on scan height when finding a free slot.

    ``header`` is a single row; rail/dock/grid can grow further. The cap
    exists so searching an empty dashboard doesn't iterate forever — 40
    rows is generous for any real layout.
    """
    if zone == "header":
        return 1
    return 40


def default_size_for_zone(zone: ChatZone) -> tuple[int, int]:
    """Sensible default ``(w, h)`` for a new pin landing in this zone.

    - ``grid``    → 6×6 tile (matches ``dashboard_pins._default_grid_layout``).
    - ``rail`` / ``dock`` → 1×4 vertical strip (single column, medium height).
    - ``header``  → 2×1 chip.
    """
    if zone == "grid":
        return (6, 6)
    if zone == "header":
        return (2, 1)
    return (1, 4)


def resolve_preset_name(grid_config: dict | None) -> str:
    """Public wrapper around the preset resolver for external callers."""
    return _resolve_preset_name(grid_config)


def find_free_slot(
    pins_in_zone: list[dict[str, Any]],
    *,
    zone: ChatZone,
    w: int,
    h: int,
    preset_name: str = _DEFAULT_PRESET,
) -> tuple[int, int]:
    """Find the smallest ``(y, x)`` where a ``w×h`` pin fits without overlap.

    Scan is row-major: increment x inside each row, then move to the next
    row. This mirrors how a human reads a layout and keeps new pins
    clustered toward the top-left — predictable for the agent proposing
    placements.
    """
    cols = _zone_cols(zone, preset_name)
    max_rows = _zone_max_rows(zone, preset_name)

    w = max(1, w)
    h = max(1, h)
    if w > cols:
        # Clamp — don't error. The agent may pass a nonsense width on a
        # rail zone; clamping yields a usable placement instead.
        w = cols

    # Figure out how tall the existing layout already is so we know the
    # minimum height our occupancy grid must cover.
    existing_max_y = 0
    for pin in pins_in_zone:
        c = _pin_coords(pin)
        existing_max_y = max(existing_max_y, c["y"] + c["h"])
    scan_rows = min(max_rows, max(existing_max_y + h, h))
    # Ensure at least h rows to consider even on an empty zone.
    scan_rows = max(scan_rows, h)

    occ = _occupancy(pins_in_zone, cols=cols, rows=scan_rows)

    def _fits(y: int, x: int) -> bool:
        if x + w > cols or y + h > scan_rows:
            return False
        for dy in range(h):
            for dx in range(w):
                if occ[y + dy][x + dx] != _EMPTY_CELL:
                    return False
        return True

    for y in range(scan_rows - h + 1):
        for x in range(cols - w + 1):
            if _fits(y, x):
                return (y, x)

    # Nothing fit in the scanned range — fall back to stacking below.
    return (existing_max_y, 0)
