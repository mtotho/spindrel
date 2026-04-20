"""Python mirror of the frontend grid presets in `ui/src/lib/dashboardGrid.ts`.

Only the subset needed for server-side zone classification lives here. A drift
guard test (`tests/unit/test_grid_preset_parity.py`) parses the TS source and
asserts these constants stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GridPresetId = Literal["standard", "fine"]


@dataclass(frozen=True)
class GridPresetFields:
    """Subset of GridPreset needed for classify_pin.

    Matches the shape of `ui/src/lib/dashboardGrid.ts::GridPreset` for the
    fields that drive zone geometry. `dock_right_cols` is Python-new; the TS
    side gains the same field in this session.
    """

    cols_lg: int
    rail_zone_cols: int
    dock_right_cols: int


GRID_PRESETS: dict[GridPresetId, GridPresetFields] = {
    "standard": GridPresetFields(cols_lg=12, rail_zone_cols=3, dock_right_cols=3),
    "fine": GridPresetFields(cols_lg=24, rail_zone_cols=6, dock_right_cols=6),
}


DEFAULT_PRESET_ID: GridPresetId = "standard"


def resolve_preset(grid_config: dict | None) -> GridPresetFields:
    if not isinstance(grid_config, dict):
        return GRID_PRESETS[DEFAULT_PRESET_ID]
    preset_id = grid_config.get("preset")
    if preset_id in GRID_PRESETS:
        return GRID_PRESETS[preset_id]  # type: ignore[index]
    return GRID_PRESETS[DEFAULT_PRESET_ID]
