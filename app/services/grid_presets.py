"""Python mirror of the frontend grid presets in `ui/src/lib/dashboardGrid.ts`.

Only the subset needed server-side lives here. Zone membership is stored
directly on each pin (``widget_dashboard_pins.zone``) and no longer derived
from preset column widths, so only the Main Grid's ``cols_lg`` survives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GridPresetId = Literal["standard", "fine"]


@dataclass(frozen=True)
class GridPresetFields:
    cols_lg: int


GRID_PRESETS: dict[GridPresetId, GridPresetFields] = {
    "standard": GridPresetFields(cols_lg=12),
    "fine": GridPresetFields(cols_lg=24),
}


DEFAULT_PRESET_ID: GridPresetId = "standard"


def resolve_preset(grid_config: dict | None) -> GridPresetFields:
    if not isinstance(grid_config, dict):
        return GRID_PRESETS[DEFAULT_PRESET_ID]
    preset_id = grid_config.get("preset")
    if preset_id in GRID_PRESETS:
        return GRID_PRESETS[preset_id]  # type: ignore[index]
    return GRID_PRESETS[DEFAULT_PRESET_ID]
