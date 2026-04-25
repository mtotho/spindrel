import { Box } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { InteractiveHtmlRenderer } from "../chat/renderers/InteractiveHtmlRenderer";
import type { ToolResultEnvelope } from "../../types/api";
import type { SpatialNodePin } from "../../api/hooks/useWorkspaceSpatial";

/**
 * Widget tile with three semantic-zoom levels (P3b — live).
 *
 *   - **Chip** at zoom < 0.4 — small icon-only square so the constellation
 *     pattern stays parseable when fully zoomed out.
 *   - **Chip + title** at 0.4 ≤ z < 0.6 — icon plus display label.
 *   - **Card** at z ≥ 0.6 — drag-handle chrome strip on top + live
 *     `<InteractiveHtmlRenderer>` body when in viewport. Out-of-viewport tiles
 *     fall back to a static body so we don't mount iframes for tiles the user
 *     can't see (P3b culling). The 0.6 threshold doubles as the live-iframe
 *     activation threshold and the cull threshold — one boundary, fewer knobs.
 *
 * Gesture shield (P3b):
 *   - Top chrome strip is always pannable / drag-handle for canvas pan +
 *     dnd-kit reposition.
 *   - Iframe body is covered by a transparent shield until the tile is
 *     "activated" (click). Shield click → activate; canvas pan still works
 *     via the chrome strip. When activated the shield is removed and the
 *     iframe takes pointer events directly. Esc / click-outside (handled
 *     by the parent canvas) deactivates.
 */

interface WidgetTileProps {
  pin: SpatialNodePin;
  zoom: number;
  /** True when the tile's world-bounds intersect the camera's viewport
   *  (with a 1-viewport margin). Iframe mounts only when this is true and
   *  zoom ≥ 0.6 — culling keeps iframe count bounded as the user pans. */
  inViewport: boolean;
  /** True when this tile is the active iframe-interaction target. Owner
   *  (canvas) tracks one activated tile at a time. */
  activated: boolean;
  /** Tile id (canvas uses this to set the activated tile). */
  nodeId: string;
  onActivate: (nodeId: string) => void;
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

export function WidgetTile({
  pin,
  zoom,
  inViewport,
  activated,
  nodeId,
  onActivate,
}: WidgetTileProps) {
  if (zoom < CHIP_THRESHOLD) return <ChipView />;
  if (zoom < TITLE_THRESHOLD) return <ChipTitleView pin={pin} />;
  return (
    <CardView
      pin={pin}
      inViewport={inViewport}
      activated={activated}
      nodeId={nodeId}
      onActivate={onActivate}
    />
  );
}

function ChipView() {
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

function CardView({
  pin,
  inViewport,
  activated,
  nodeId,
  onActivate,
}: {
  pin: SpatialNodePin;
  inViewport: boolean;
  activated: boolean;
  nodeId: string;
  onActivate: (id: string) => void;
}) {
  const t = useThemeTokens();
  const title = widgetTitle(pin);
  const tool = bareToolName(pin.tool_name);
  const liveIframe = inViewport;

  return (
    <div
      data-tile-kind="widget"
      className={`w-full h-full rounded-xl border bg-surface-raised text-text shadow-lg flex flex-col cursor-grab active:cursor-grabbing overflow-hidden ${
        activated ? "border-accent" : "border-surface-border"
      }`}
    >
      {/* Drag-handle chrome strip — always pannable / dnd-kit drag handle.
          Stops propagation on activation-state changes so clicking the strip
          doesn't bubble to the iframe shield below. */}
      <div className="flex flex-row items-center gap-1.5 px-3 py-2 border-b border-surface-border bg-surface-raised flex-shrink-0">
        <Box size={11} className="text-text-dim" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">
          Widget
        </span>
        <span className="text-sm font-semibold leading-tight truncate ml-1">
          {title}
        </span>
        <span className="text-[10px] text-text-dim font-mono truncate ml-auto">
          {tool}
        </span>
      </div>

      {/* Iframe body (or static fallback when culled). */}
      <div className="flex-1 relative bg-surface min-h-0 overflow-hidden">
        {liveIframe ? (
          <>
            {/* When activated, stop pointerdown from reaching dnd-kit so the
                user can interact with the iframe (drag inside it, scroll,
                etc.) without starting a tile reposition. */}
            <div
              className="absolute inset-0"
              onPointerDown={
                activated ? (e) => e.stopPropagation() : undefined
              }
            >
              <InteractiveHtmlRenderer
                envelope={pin.envelope as unknown as ToolResultEnvelope}
                channelId={pin.source_channel_id ?? undefined}
                dashboardPinId={pin.id}
                fillHeight
                hostSurface="plain"
                t={t}
              />
            </div>

            {/* Transparent shield — blocks iframe pointer events until the
                tile is activated. Click → activate. Pointerdown stopped to
                avoid starting a dnd-kit drag on a clean tap (4px activation
                distance handles drag intent). */}
            {!activated && (
              <button
                type="button"
                aria-label="Activate widget"
                title="Click to interact"
                onClick={(e) => {
                  e.stopPropagation();
                  onActivate(nodeId);
                }}
                onDoubleClick={(e) => e.stopPropagation()}
                className="absolute inset-0 cursor-pointer bg-transparent border-0 p-0 m-0"
              />
            )}
          </>
        ) : (
          <StaticBody pin={pin} />
        )}
      </div>

      {!activated && liveIframe && (
        <div className="text-[10px] text-text-dim text-center py-1 border-t border-surface-border flex-shrink-0">
          Click to interact · Esc to release
        </div>
      )}
    </div>
  );
}

function StaticBody({ pin }: { pin: SpatialNodePin }) {
  return (
    <div className="w-full h-full flex flex-col gap-2 p-3">
      <div className="text-[11px] text-text-dim font-mono truncate">
        {bareToolName(pin.tool_name)}
      </div>
      {pin.source_bot_id && (
        <div className="text-[10px] text-text-dim mt-auto truncate">
          via {pin.source_bot_id}
        </div>
      )}
    </div>
  );
}
