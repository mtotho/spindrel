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
import rawPresetManifest from "../../../packages/dashboard-grid/presets.json";
export const DEFAULT_CHROME = {
    borderless: false,
    hoverScrollbars: true,
    hideTitles: false,
};
export function resolveChrome(grid_config) {
    if (!grid_config || typeof grid_config !== "object")
        return DEFAULT_CHROME;
    const cfg = grid_config;
    return {
        borderless: cfg.borderless === true,
        hoverScrollbars: cfg.hover_scrollbars !== false,
        hideTitles: cfg.hide_titles === true,
    };
}
export function resolveShowTitle(chrome, widgetConfig) {
    const raw = widgetConfig?.show_title;
    if (raw === "show")
        return true;
    if (raw === "hide")
        return false;
    return !chrome.hideTitles;
}
export function resolveWrapperSurface(chrome, widgetConfig) {
    const raw = widgetConfig?.wrapper_surface;
    if (raw === "surface")
        return "surface";
    if (raw === "plain")
        return "plain";
    return chrome.borderless ? "plain" : "surface";
}
const presetManifest = rawPresetManifest;
export const GRID_PRESETS = presetManifest.presets;
export const DEFAULT_PRESET_ID = presetManifest.defaultPresetId;
/** Compute the pixel width/height a pin occupies given its grid layout,
 *  the dashboard preset, the measured container width, and the RGL margin.
 *  Used as a fallback when a caller knows its grid cell math up front but
 *  hasn't measured the DOM yet (e.g. for pre-sizing an iframe skeleton so
 *  it matches the cell on first paint rather than popping from 200px).
 *  ``containerWidth`` should be the RGL container's pixel width; ``margin``
 *  is the tuple passed to the ``<ResponsiveGridLayout>`` component. */
export function computePinPixelSize(gridLayout, preset, containerWidth, margin = [12, 12]) {
    const w = gridLayout?.w;
    const h = gridLayout?.h;
    if (!w || !h || !containerWidth || containerWidth <= 0)
        return null;
    const cols = preset.cols.lg;
    const [marginX, marginY] = margin;
    const totalGap = marginX * (cols + 1);
    const colWidth = (containerWidth - totalGap) / cols;
    if (!Number.isFinite(colWidth) || colWidth <= 0)
        return null;
    const width = colWidth * w + marginX * (w - 1);
    const height = preset.rowHeight * h + marginY * (h - 1);
    return { width: Math.max(0, width), height: Math.max(0, height) };
}
/** Resolve a dashboard's preset from its `grid_config`. Null / malformed
 *  values fall back to the default preset. */
export function resolvePreset(grid_config) {
    if (grid_config
        && typeof grid_config === "object"
        && "preset" in grid_config
        && typeof grid_config.preset === "string"
        && grid_config.preset in GRID_PRESETS) {
        return GRID_PRESETS[grid_config.preset];
    }
    return GRID_PRESETS[DEFAULT_PRESET_ID];
}
