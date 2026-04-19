/** Per-dashboard layout presets. Source of truth for frontend grid math.
 *
 *  A dashboard's `grid_config` JSONB is shaped
 *  `{ layout_type: "grid", preset: "standard" | "fine" }`. Existing rows
 *  with NULL grid_config fall back to `standard` — the legacy layout.
 *
 *  When a user switches presets on an existing dashboard, the BACKEND
 *  rescales every pin's `grid_layout` by the ratio between preset col
 *  counts (see `app/services/dashboards.py::_scale_ratio`). Frontend just
 *  reads `preset` and picks the right column/row/tile constants.
 */

export type GridLayoutType = "grid";
export type GridPresetId = "standard" | "fine";

export interface GridConfig {
  layout_type: GridLayoutType;
  preset: GridPresetId;
}

export interface GridPreset {
  id: GridPresetId;
  label: string;
  description: string;
  cols: { lg: number; md: number; sm: number; xs: number; xxs: number };
  rowHeight: number;
  defaultTile: { w: number; h: number };
  minTile: { w: number; h: number };
  /** Column count of the leftmost "rail zone" — pins whose left edge sits
   *  inside this band (`grid_layout.x < railZoneCols`) surface in the
   *  channel's OmniPanel sidebar. Sized as ~1/4 of the full grid so a
   *  "full rail width" widget on the dashboard matches the sidebar's
   *  physical width close to 1:1 — otherwise users would need to size
   *  widgets huge on the dashboard just to fill the sidebar. */
  railZoneCols: number;
}

export const GRID_PRESETS: Record<GridPresetId, GridPreset> = {
  standard: {
    id: "standard",
    label: "Standard",
    description: "12-column grid, 30px rows. Good for most dashboards.",
    cols: { lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 },
    rowHeight: 30,
    defaultTile: { w: 3, h: 6 },
    minTile: { w: 2, h: 3 },
    railZoneCols: 3,
  },
  fine: {
    id: "fine",
    label: "Fine",
    description:
      "24-column grid, 15px rows. Twice as granular — snap to finer positions.",
    cols: { lg: 24, md: 20, sm: 12, xs: 8, xxs: 4 },
    rowHeight: 15,
    defaultTile: { w: 6, h: 12 },
    minTile: { w: 4, h: 6 },
    railZoneCols: 6,
  },
};

export const DEFAULT_PRESET_ID: GridPresetId = "standard";

/** Resolve a dashboard's preset from its `grid_config`. Null / malformed
 *  values fall back to the default preset. */
export function resolvePreset(grid_config: unknown): GridPreset {
  if (
    grid_config
    && typeof grid_config === "object"
    && "preset" in grid_config
    && typeof (grid_config as { preset?: unknown }).preset === "string"
    && (grid_config as { preset: string }).preset in GRID_PRESETS
  ) {
    return GRID_PRESETS[(grid_config as { preset: GridPresetId }).preset];
  }
  return GRID_PRESETS[DEFAULT_PRESET_ID];
}
