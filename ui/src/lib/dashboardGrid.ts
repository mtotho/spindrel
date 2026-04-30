/** Per-dashboard layout presets. Frontend projection of the shared manifest.
 *
 *  A dashboard's `grid_config` JSONB is shaped
 *  `{ layout_type: "grid", preset: "standard" | "fine" }`. Existing rows
 *  with NULL grid_config fall back to `standard` — the legacy layout.
 *
 *  When a user switches presets on an existing dashboard, the BACKEND
 *  rescales every pin's `grid_layout` by the ratio between preset col
 *  counts. Frontend just reads `preset` and picks the right column/row/tile
 *  constants.
 */

import type { ChatZone } from "@/src/types/api";
import rawPresetManifest from "../../../packages/dashboard-grid/presets.json";
export type { ChatZone };

export type GridLayoutType = "grid";
export type GridPresetId = keyof typeof rawPresetManifest.presets;

export interface GridConfig {
  layout_type: GridLayoutType;
  preset: GridPresetId;
  borderless?: boolean;
  hover_scrollbars?: boolean;
  hide_titles?: boolean;
  canvas_mode?: string;
  canvas_origin_x?: number;
  canvas_origin_y?: number;
  [key: string]: unknown;
}

export interface DashboardChrome {
  borderless: boolean;
  hoverScrollbars: boolean;
  hideTitles: boolean;
}

/** Per-pin override for the host wrapper surface.
 *  - "inherit" (default): follow the host chrome default
 *  - "surface": force the host wrapper to render its outer surface
 *  - "plain": force a transparent/minimal host wrapper
 */
export type WrapperSurfaceOverride = "inherit" | "surface" | "plain";

export const DEFAULT_CHROME: DashboardChrome = {
  borderless: false,
  hoverScrollbars: true,
  hideTitles: false,
};

export function resolveChrome(grid_config: unknown): DashboardChrome {
  if (!grid_config || typeof grid_config !== "object") return DEFAULT_CHROME;
  const cfg = grid_config as Record<string, unknown>;
  return {
    borderless: cfg.borderless === true,
    hoverScrollbars: cfg.hover_scrollbars !== false,
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

export function resolveWrapperSurface(
  chrome: DashboardChrome,
  widgetConfig: Record<string, unknown> | null | undefined,
): "surface" | "plain" {
  const raw = widgetConfig?.wrapper_surface;
  if (raw === "surface") return "surface";
  if (raw === "plain") return "plain";
  return chrome.borderless ? "plain" : "surface";
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

type GridPresetManifest = {
  defaultPresetId: GridPresetId;
  presets: Record<GridPresetId, GridPreset>;
};

const presetManifest = rawPresetManifest as GridPresetManifest;

export const GRID_PRESETS: Record<GridPresetId, GridPreset> = presetManifest.presets;
export const DEFAULT_PRESET_ID: GridPresetId = presetManifest.defaultPresetId;

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
