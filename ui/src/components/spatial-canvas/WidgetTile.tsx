import { Box } from "lucide-react";
import type { SpatialNodePin } from "../../api/hooks/useWorkspaceSpatial";

/**
 * Widget tile with three semantic-zoom levels (P3a — static).
 *
 *   - **Chip** at zoom < 0.4 — small icon-only square so the constellation
 *     pattern stays parseable when fully zoomed out.
 *   - **Chip + title** at 0.4 ≤ z < 0.6 — icon plus display label.
 *   - **Card** at z ≥ 0.6 — expanded card with display label, tool name,
 *     source bot. Static — the live iframe at this zoom level lands in
 *     **P3b** (iframe + gesture shield + culling + keepalive). The same
 *     zoom threshold (0.6) doubles as the future culling threshold so
 *     tile work and iframe work share one boundary.
 */

interface WidgetTileProps {
  pin: SpatialNodePin;
  zoom: number;
}

const CHIP_THRESHOLD = 0.4;
const TITLE_THRESHOLD = 0.6;

function widgetTitle(pin: SpatialNodePin): string {
  return (
    pin.panel_title?.trim() ||
    pin.display_label?.trim() ||
    bareToolName(pin.tool_name)
  );
}

function bareToolName(toolName: string): string {
  // Skill-prefixed tools come through as `skill-toolname`; show only the
  // tool half in compact contexts.
  const idx = toolName.indexOf("-");
  return idx >= 0 ? toolName.slice(idx + 1) : toolName;
}

export function WidgetTile({ pin, zoom }: WidgetTileProps) {
  if (zoom < CHIP_THRESHOLD) return <ChipView pin={pin} />;
  if (zoom < TITLE_THRESHOLD) return <ChipTitleView pin={pin} />;
  return <CardView pin={pin} />;
}

function ChipView({ pin: _pin }: { pin: SpatialNodePin }) {
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full flex flex-col items-center justify-center cursor-grab active:cursor-grabbing"
    >
      <div className="w-10 h-10 rounded-lg bg-surface-raised border border-surface-border flex flex-row items-center justify-center text-text-dim shadow-md">
        <Box size={18} />
      </div>
    </div>
  );
}

function ChipTitleView({ pin }: { pin: SpatialNodePin }) {
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full flex flex-col items-center justify-center gap-1.5 cursor-grab active:cursor-grabbing"
    >
      <div className="w-9 h-9 rounded-lg bg-surface-raised border border-surface-border flex flex-row items-center justify-center text-text-dim shadow-md">
        <Box size={16} />
      </div>
      <div className="text-xs font-medium text-text whitespace-nowrap max-w-full truncate px-2">
        {widgetTitle(pin)}
      </div>
    </div>
  );
}

function CardView({ pin }: { pin: SpatialNodePin }) {
  const title = widgetTitle(pin);
  const tool = bareToolName(pin.tool_name);
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full rounded-xl border border-surface-border bg-surface-raised text-text shadow-lg flex flex-col gap-2 p-3 cursor-grab active:cursor-grabbing overflow-hidden"
    >
      <div className="flex flex-row items-center gap-1.5 text-[10px] tracking-wider text-text-dim uppercase">
        <Box size={11} />
        <span>Widget</span>
      </div>
      <div className="text-sm font-semibold leading-tight truncate">{title}</div>
      <div className="text-[11px] text-text-dim font-mono truncate">{tool}</div>
      {pin.source_bot_id && (
        <div className="text-[10px] text-text-dim mt-auto truncate">
          via {pin.source_bot_id}
        </div>
      )}
    </div>
  );
}
