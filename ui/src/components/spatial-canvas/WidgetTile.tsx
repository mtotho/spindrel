import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens } from "../../theme/tokens";
import { InteractiveHtmlRenderer } from "../chat/renderers/InteractiveHtmlRenderer";
import { ComponentRenderer, WidgetActionContext } from "../chat/renderers/ComponentRenderer";
import { renderNativeWidget } from "../chat/renderers/nativeApps/registry";
import type { ToolResultEnvelope } from "../../types/api";
import {
  NODES_KEY,
  useDeleteSpatialNode,
  useUpdateSpatialNode,
  type SpatialNode,
  type SpatialNodePin,
} from "../../api/hooks/useWorkspaceSpatial";
import { useWidgetAction } from "../../api/hooks/useWidgetAction";
import type { WidgetActionResult } from "../../api/hooks/useWidgetAction";
import { usePinnedWidgetsStore, envelopeIdentityKey } from "../../stores/pinnedWidgets";

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

const MIN_W = 200;
const MIN_H = 140;

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
  if (zoom < TITLE_THRESHOLD) return <ChipTitleView pin={pin} zoom={zoom} />;
  return (
    <CardView
      pin={pin}
      inViewport={inViewport}
      activated={activated}
      nodeId={nodeId}
      onActivate={onActivate}
      zoom={zoom}
    />
  );
}

/**
 * Diamond glyph (rotated 45° square) — distinct silhouette from the
 * channel `dot` so the user reads "widget" vs "channel" at any zoom level.
 * The icon counter-rotates to stay upright.
 */
function WidgetGlyph({ size }: { size: number }) {
  return (
    <div
      className="bg-accent/15 border-2 border-accent shadow-md flex items-center justify-center text-accent"
      style={{
        width: size,
        height: size,
        transform: "rotate(45deg)",
        borderRadius: 6,
      }}
    >
      <div style={{ transform: "rotate(-45deg)" }}>
        <Box size={Math.round(size * 0.45)} />
      </div>
    </div>
  );
}

function ChipView() {
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full flex flex-col items-center justify-center cursor-grab active:cursor-grabbing"
    >
      <WidgetGlyph size={64} />
    </div>
  );
}

function ChipTitleView({ pin, zoom }: { pin: SpatialNodePin; zoom: number }) {
  // Counter-scale the title so it stays readable at chip+title zoom range
  // (0.4 ≤ z < 0.6). Same trick as channel DotView.
  const labelScale = Math.min(3, 1 / Math.max(0.05, zoom));
  return (
    <div
      data-tile-kind="widget"
      className="w-full h-full flex flex-col items-center justify-center gap-3 cursor-grab active:cursor-grabbing"
    >
      <WidgetGlyph size={56} />
      <div
        className="text-base font-semibold text-text whitespace-nowrap max-w-full truncate px-2"
        style={{
          transform: `scale(${labelScale})`,
          transformOrigin: "center top",
        }}
      >
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
  zoom,
}: {
  pin: SpatialNodePin;
  inViewport: boolean;
  activated: boolean;
  nodeId: string;
  onActivate: (id: string) => void;
  zoom: number;
}) {
  const t = useThemeTokens();
  const title = widgetTitle(pin);
  const tool = bareToolName(pin.tool_name);
  // Three body shapes the canvas may host — same dispatch as
  // `RichToolResult` / `WidgetCard`:
  //   1. `html+interactive` → sandboxed iframe + gesture shield.
  //   2. `native-app+json`  → registry component (Notes, Todo, etc.) — DOM
  //      tree with its own state machine + dispatchNativeAction.
  //   3. `components+json`  → ComponentRenderer wrapped in WidgetActionContext
  //      so component-level actions (HA toggle, etc.) dispatch through
  //      `useWidgetAction` against the canvas pin.
  // Earlier code force-fed every envelope through InteractiveHtmlRenderer,
  // which printed component/native bodies as raw JSON.
  const envelope = pin.envelope as unknown as ToolResultEnvelope;
  const ct = envelope.content_type;
  const isHtmlWidget = ct === "application/vnd.spindrel.html+interactive";
  const isNativeWidget = ct === "application/vnd.spindrel.native-app+json";
  const live = inViewport;

  // Local envelope state — component-widget action results return a fresh
  // envelope; we track it here and re-render the body. Native widgets manage
  // their own envelope state internally via `useNativeEnvelopeState`.
  const [currentEnvelope, setCurrentEnvelope] = useState<ToolResultEnvelope>(envelope);
  // Reset when the upstream pin payload changes (e.g. another surface
  // updated this widget and the spatial-nodes query invalidated).
  useEffect(() => {
    setCurrentEnvelope(envelope);
  }, [envelope]);

  const rawBody = currentEnvelope.body;
  const componentBody =
    rawBody == null
      ? ""
      : typeof rawBody === "string"
      ? rawBody
      : JSON.stringify(rawBody);

  // Component-widget action context. Wires through the canvas pin id as
  // `dashboardPinId` so widget_config dispatch persists onto this exact
  // canvas pin (decision 4: world pins are independent rows).
  const channelId = pin.source_channel_id ?? undefined;
  const broadcastEnvelope = usePinnedWidgetsStore((s) => s.broadcastEnvelope);
  const rawDispatch = useWidgetAction(
    channelId,
    pin.source_bot_id ?? "default",
    currentEnvelope.display_label ?? null,
    null,
    pin.widget_config ?? null,
    pin.id,
  );
  const interceptingDispatch = useCallback(
    async (
      action: import("../../types/api").WidgetAction,
      value: unknown,
    ): Promise<WidgetActionResult> => {
      const result = await rawDispatch(action, value);
      if (
        result.envelope
        && result.envelope.content_type === "application/vnd.spindrel.components+json"
        && result.envelope.body
      ) {
        setCurrentEnvelope(result.envelope);
        if (channelId) {
          broadcastEnvelope(channelId, pin.tool_name, result.envelope, {
            kind: "tool_result",
          });
        }
      }
      return result;
    },
    [rawDispatch, channelId, pin.tool_name, broadcastEnvelope],
  );
  const actionCtx = useMemo(
    () => (channelId ? { dispatchAction: interceptingDispatch } : null),
    [channelId, interceptingDispatch],
  );

  // Cross-surface envelope sync — same pattern as WidgetCard. When another
  // surface (chat / dashboard / rail) updates this widget, the shared
  // store key has the latest envelope; we adopt it.
  const envelopeKey = channelId
    ? `${channelId}::${envelopeIdentityKey(pin.tool_name, currentEnvelope, pin.widget_config ?? null)}`
    : null;
  const sharedEnvelope = usePinnedWidgetsStore((s) =>
    envelopeKey ? s.widgetEnvelopes[envelopeKey] : undefined,
  );
  const envelopeRef = useRef(currentEnvelope);
  envelopeRef.current = currentEnvelope;
  useEffect(() => {
    if (sharedEnvelope && sharedEnvelope.envelope !== envelopeRef.current) {
      setCurrentEnvelope(sharedEnvelope.envelope);
    }
  }, [sharedEnvelope]);

  const deleteNode = useDeleteSpatialNode();

  return (
    <div
      data-tile-kind="widget"
      className={`group relative w-full h-full rounded-xl border bg-surface-raised text-text shadow-lg flex flex-col cursor-grab active:cursor-grabbing overflow-hidden ${
        activated ? "border-accent" : "border-surface-border"
      }`}
    >
      {/* Drag-handle chrome strip — always pannable / dnd-kit drag handle.
          The unpin "X" is hover-reveal so calm tiles stay calm. */}
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
        <button
          type="button"
          aria-label="Remove from canvas"
          title="Remove from canvas"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            deleteNode.mutate(nodeId);
          }}
          className="ml-1 p-0.5 rounded hover:bg-text/[0.06] opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity flex-shrink-0"
        >
          <X size={11} className="text-text-dim" />
        </button>
      </div>

      {/* Body — branches on widget content type. */}
      <div className="flex-1 relative bg-surface min-h-0 overflow-hidden">
        {!live ? (
          <StaticBody pin={pin} />
        ) : isHtmlWidget ? (
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
                envelope={currentEnvelope}
                channelId={channelId}
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
        ) : isNativeWidget ? (
          // Native widgets (Notes, Todo, …) own their dispatch via
          // useNativeEnvelopeState; we just give them the right host props.
          <div
            className="absolute inset-0 overflow-y-auto"
            onPointerDown={(e) => e.stopPropagation()}
          >
            {renderNativeWidget({
              envelope: currentEnvelope,
              channelId,
              dashboardPinId: pin.id,
              hostSurface: "plain",
              t,
            })}
          </div>
        ) : (
          // Component widgets — DOM tree wrapped in WidgetActionContext so
          // toggles / buttons / sliders dispatch through the canvas pin.
          <div
            className="absolute inset-0 overflow-y-auto"
            onPointerDown={(e) => e.stopPropagation()}
          >
            {actionCtx ? (
              <WidgetActionContext.Provider value={actionCtx}>
                <ComponentRenderer
                  body={componentBody}
                  layout={undefined}
                  hostSurface="plain"
                  t={t}
                />
              </WidgetActionContext.Provider>
            ) : (
              <ComponentRenderer
                body={componentBody}
                layout={undefined}
                hostSurface="plain"
                t={t}
              />
            )}
          </div>
        )}
      </div>

      {!activated && live && isHtmlWidget && (
        <div className="text-[10px] text-text-dim text-center py-1 border-t border-surface-border flex-shrink-0">
          Click to interact · Esc to release
        </div>
      )}

      <ResizeHandle nodeId={nodeId} zoom={zoom} />
    </div>
  );
}

/**
 * Bottom-right corner resize handle. Live preview via React Query
 * optimistic cache (overwrite the cached node's `world_w/h` on each
 * pointermove tick — re-render is automatic). On pointerup the new size
 * commits via the same `useUpdateSpatialNode` mutation that drag-reposition
 * uses; the mutation's onSettled invalidate keeps everything coherent.
 *
 * Stops pointerdown propagation so dnd-kit doesn't start a tile reposition
 * while the user is grabbing the corner.
 */
function ResizeHandle({ nodeId, zoom }: { nodeId: string; zoom: number }) {
  const qc = useQueryClient();
  const update = useUpdateSpatialNode();
  const startRef = useRef<{
    x: number;
    y: number;
    w: number;
    h: number;
    pointerId: number;
  } | null>(null);

  const findNode = (): SpatialNode | undefined => {
    const nodes = qc.getQueryData<SpatialNode[]>(NODES_KEY) ?? [];
    return nodes.find((n) => n.id === nodeId);
  };

  return (
    <div
      role="presentation"
      aria-label="Resize widget"
      title="Drag to resize"
      className="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
      style={{
        background:
          "linear-gradient(135deg, transparent 0%, transparent 50%, rgb(var(--color-text-dim) / 0.6) 50%, rgb(var(--color-text-dim) / 0.6) 60%, transparent 60%, transparent 75%, rgb(var(--color-text-dim) / 0.6) 75%, rgb(var(--color-text-dim) / 0.6) 85%, transparent 85%)",
      }}
      onPointerDown={(e) => {
        const node = findNode();
        if (!node) return;
        e.stopPropagation();
        e.preventDefault();
        startRef.current = {
          x: e.clientX,
          y: e.clientY,
          w: node.world_w,
          h: node.world_h,
          pointerId: e.pointerId,
        };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        const s = startRef.current;
        if (!s || s.pointerId !== e.pointerId) return;
        const newW = Math.max(MIN_W, s.w + (e.clientX - s.x) / zoom);
        const newH = Math.max(MIN_H, s.h + (e.clientY - s.y) / zoom);
        qc.setQueryData<SpatialNode[]>(NODES_KEY, (old) =>
          (old ?? []).map((n) =>
            n.id === nodeId ? { ...n, world_w: newW, world_h: newH } : n,
          ),
        );
      }}
      onPointerUp={(e) => {
        const s = startRef.current;
        if (!s || s.pointerId !== e.pointerId) return;
        startRef.current = null;
        const node = findNode();
        if (node && (node.world_w !== s.w || node.world_h !== s.h)) {
          update.mutate({
            nodeId,
            body: { world_w: node.world_w, world_h: node.world_h },
          });
        }
        try {
          e.currentTarget.releasePointerCapture(e.pointerId);
        } catch {
          /* already released */
        }
      }}
    />
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
