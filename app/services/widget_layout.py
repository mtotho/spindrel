"""Widget layout — single source of truth for ``layout_hints`` semantics.

A widget author declares intent in its manifest::

    layout_hints:
      preferred_zone: "grid"     # grid | rail | header | dock | chip
      min_cells: {w: 2, h: 1}
      max_cells: {w: 6, h: 4}

Before Cluster 4B.3 that intent was parsed in two files:
- ``widget_contracts.py::normalize_layout_hints`` (shape normalization)
- ``dashboard_pins.py::_resolve_zone_from_layout_hints`` /
  ``_clamp_layout_size_to_hints`` / ``_VALID_ZONES`` (runtime use)

Callers had to know which module to ask. This module is the deep
module: one home for the hint vocabulary, the valid zone set, and the
two runtime decisions (zone resolution, size clamp).

Grid mechanics (position → default (w,h), normalize-to-preset-cols)
remain in ``dashboard_pins.py`` because they depend on per-dashboard
preset config. The seam is deliberate — widget authors declare
*intent* here; *mechanics* of rendering into a specific grid stay
with the grid owner.
"""
from __future__ import annotations

from typing import Any

# The zones a pin can live in. ``chip`` is an alias for ``header`` —
# widget authors can write ``preferred_zone: chip`` and the resolver
# rewrites it to ``header``.
VALID_ZONES: frozenset[str] = frozenset({"rail", "header", "dock", "grid"})


def normalize_layout_hints(hints: object) -> dict[str, Any] | None:
    """Return a clean copy of ``layout_hints`` with unknown keys dropped,
    or ``None`` if the input isn't a dict / has no recognized keys.

    Used when building a pin's ``widget_presentation`` snapshot so the
    persisted hints don't drift from the manifest-declared vocabulary.
    """
    if not isinstance(hints, dict):
        return None
    out: dict[str, Any] = {}
    preferred = hints.get("preferred_zone")
    if isinstance(preferred, str) and preferred.strip():
        out["preferred_zone"] = preferred.strip()
    for key in ("min_cells", "max_cells"):
        raw = hints.get(key)
        if not isinstance(raw, dict):
            continue
        cells = {
            dim: int(value)
            for dim, value in raw.items()
            if dim in {"w", "h"} and isinstance(value, int) and value > 0
        }
        if cells:
            out[key] = cells
    return out or None


def resolve_zone_from_layout_hints(layout_hints: object) -> str | None:
    """Return the zone the widget wants to pin into, or ``None`` when
    the hints don't speak to zone placement.

    ``preferred_zone: "chip"`` is rewritten to ``"header"`` — chip is
    the author-facing vocabulary; header is the dashboard-internal
    zone name.
    """
    if not isinstance(layout_hints, dict):
        return None
    preferred_zone = layout_hints.get("preferred_zone")
    if not isinstance(preferred_zone, str):
        return None
    normalized = preferred_zone.strip()
    if normalized == "chip":
        return "header"
    if normalized in VALID_ZONES:
        return normalized
    return None


def clamp_layout_size_to_hints(
    layout: dict[str, int],
    *,
    layout_hints: object,
) -> dict[str, int]:
    """Return a copy of ``layout`` with ``w``/``h`` clamped to any
    ``min_cells`` / ``max_cells`` declared in ``layout_hints``.

    No-op when ``layout_hints`` isn't a dict or has no size bounds.
    """
    if not isinstance(layout_hints, dict):
        return dict(layout)
    width = layout.get("w", 1)
    height = layout.get("h", 1)
    min_cells = layout_hints.get("min_cells")
    max_cells = layout_hints.get("max_cells")
    min_w = _cell_hint_value(min_cells, "w")
    min_h = _cell_hint_value(min_cells, "h")
    max_w = _cell_hint_value(max_cells, "w")
    max_h = _cell_hint_value(max_cells, "h")
    if min_w is not None:
        width = max(width, min_w)
    if min_h is not None:
        height = max(height, min_h)
    if max_w is not None:
        width = min(width, max_w)
    if max_h is not None:
        height = min(height, max_h)
    next_layout = dict(layout)
    next_layout["w"] = width
    next_layout["h"] = height
    return next_layout


def validate_zone(zone: str) -> None:
    """Raise ``ValueError`` if ``zone`` isn't a valid dashboard zone.

    Callers (``dashboard_pins.create_pin`` etc.) convert the
    ``ValueError`` to their own domain error at the boundary.
    """
    if zone not in VALID_ZONES:
        raise ValueError(f"Invalid zone: {zone}")


def _cell_hint_value(source: object, key: str) -> int | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if isinstance(value, int) and value > 0:
        return value
    return None
