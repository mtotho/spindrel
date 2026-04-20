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

import type { ChatZone } from "@/src/types/api";
export type { ChatZone };

export type GridLayoutType = "grid";
export type GridPresetId = "standard" | "fine";

export interface GridConfig {
  layout_type: GridLayoutType;
  preset: GridPresetId;
  borderless?: boolean;
  hover_scrollbars?: boolean;
  hide_titles?: boolean;
}

export interface DashboardChrome {
  borderless: boolean;
  hoverScrollbars: boolean;
  hideTitles: boolean;
}

export const DEFAULT_CHROME: DashboardChrome = {
  borderless: false,
  hoverScrollbars: false,
  hideTitles: false,
};

export function resolveChrome(grid_config: unknown): DashboardChrome {
  if (!grid_config || typeof grid_config !== "object") return DEFAULT_CHROME;
  const cfg = grid_config as Record<string, unknown>;
  return {
    borderless: cfg.borderless === true,
    hoverScrollbars: cfg.hover_scrollbars === true,
    hideTitles: cfg.hide_titles === true,
  };
}

/** Per-pin override for the title bar.
 *  - "inherit" (default): follow the dashboard's `hide_titles`
 *  - "show": force visible regardless of dashboard
 *  - "hide": force hidden regardless of dashboard
 */
export type TitleVisibilityOverride = "inherit" | "show" | "hide";

export function resolveShowTitle(
  chrome: DashboardChrome,
  widgetConfig: Record<string, unknown> | null | undefined,
): boolean {
  const raw = widgetConfig?.show_title;
  if (raw === "show") return true;
  if (raw === "hide") return false;
  return !chrome.hideTitles;
}

export type SizePresetId = "S" | "M" | "L" | "XL";

export interface SizePreset {
  id: SizePresetId;
  label: string;
  w: number;
  h: number;
}

export interface GridPreset {
  id: GridPresetId;
  label: string;
  description: string;
  cols: { lg: number; md: number; sm: number; xs: number; xxs: number };
  rowHeight: number;
  defaultTile: { w: number; h: number };
  minTile: { w: number; h: number };
  /** One-click tile sizing chips surfaced in EditPinDrawer. Preset values
   *  are preset-specific — the standard grid's "S" is a 3×6 tile; the fine
   *  grid's "S" is 6×12 (same physical area, half the snap granularity). */
  sizePresets: SizePreset[];
}

export const GRID_PRESETS: Record<GridPresetId, GridPreset> = {
  standard: {
    id: "standard",
    label: "Standard",
    description: "12-column grid, 30px rows. Good for most dashboards.",
    cols: { lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 },
    rowHeight: 30,
    defaultTile: { w: 6, h: 10 },
    minTile: { w: 2, h: 3 },
    sizePresets: [
      { id: "S", label: "S", w: 3, h: 6 },
      { id: "M", label: "M", w: 4, h: 8 },
      { id: "L", label: "L", w: 6, h: 10 },
      { id: "XL", label: "XL", w: 12, h: 12 },
    ],
  },
  fine: {
    id: "fine",
    label: "Fine",
    description:
      "24-column grid, 15px rows. Twice as granular — snap to finer positions.",
    cols: { lg: 24, md: 20, sm: 12, xs: 8, xxs: 4 },
    rowHeight: 15,
    defaultTile: { w: 12, h: 20 },
    minTile: { w: 4, h: 6 },
    sizePresets: [
      { id: "S", label: "S", w: 6, h: 12 },
      { id: "M", label: "M", w: 8, h: 16 },
      { id: "L", label: "L", w: 12, h: 20 },
      { id: "XL", label: "XL", w: 24, h: 24 },
    ],
  },
};

export const DEFAULT_PRESET_ID: GridPresetId = "standard";

/** Compute the pixel width/height a pin occupies given its grid layout,
 *  the dashboard preset, the measured container width, and the RGL margin.
 *  Used as a fallback when a caller knows its grid cell math up front but
 *  hasn't measured the DOM yet (e.g. for pre-sizing an iframe skeleton so
 *  it matches the cell on first paint rather than popping from 200px).
 *  ``containerWidth`` should be the RGL container's pixel width; ``margin``
 *  is the tuple passed to the ``<ResponsiveGridLayout>`` component. */
export function computePinPixelSize(
  gridLayout: { w?: number; h?: number } | null | undefined,
  preset: GridPreset,
  containerWidth: number,
  margin: [number, number] = [12, 12],
): { width: number; height: number } | null {
  const w = gridLayout?.w;
  const h = gridLayout?.h;
  if (!w || !h || !containerWidth || containerWidth <= 0) return null;
  const cols = preset.cols.lg;
  const [marginX, marginY] = margin;
  const totalGap = marginX * (cols + 1);
  const colWidth = (containerWidth - totalGap) / cols;
  if (!Number.isFinite(colWidth) || colWidth <= 0) return null;
  const width = colWidth * w + marginX * (w - 1);
  const height = preset.rowHeight * h + marginY * (h - 1);
  return { width: Math.max(0, width), height: Math.max(0, height) };
}

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
