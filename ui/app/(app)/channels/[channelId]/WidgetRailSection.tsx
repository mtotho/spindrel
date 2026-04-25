/**
 * WidgetRailSection — shared single-column RGL grid used by both chat-mode
 * widget rails (left `OmniPanel` Widgets tab + right `WidgetDockRight`). Each
 * widget renders in dashboard scope + railMode so it fills its RGL tile height
 * instead of the channel-scope 350px cap. Drag + resize write back to the
 * channel dashboard via the shared `applyLayout` store action, preserving
 * each pin's original dashboard x/w.
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import { PinnedToolWidget } from "./PinnedToolWidget";
import type { WidgetLayout } from "@/src/components/chat/renderers/InteractiveHtmlRenderer";
import type { DashboardChrome, GridPreset } from "@/src/lib/dashboardGrid";
import type {
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";

const ResponsiveGridLayout = WidthProvider(Responsive);
const RAIL_BREAKPOINTS = { lg: 0 } as const;
const RAIL_MARGIN: [number, number] = [0, 12];
// Kill the RGL default container padding (falls back to `margin` when unset,
// which would mean 12px above the first tile and 12px below the last). Rail
// widgets should sit flush with the section's outer padding — dragging the
// top tile upward previously "bounced back" because RGL's own 12px top pad
// was below y=0 in grid space, so there was no room to move into.
const RAIL_CONTAINER_PADDING: [number, number] = [0, 0];

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    config: pin.widget_config ?? {},
  };
}

interface WidgetRailSectionProps {
  channelId: string;
  pins: WidgetDashboardPin[];
  preset: GridPreset;
  chrome: DashboardChrome;
  editable?: boolean;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  applyLayout: (
    items: Array<{ id: string; x: number; y: number; w: number; h: number }>,
  ) => Promise<void>;
  /** Host-zone classification for the widgets in this rail — ``"rail"`` for
   *  the left OmniPanel column, ``"dock"`` for the right WidgetDockRight.
   *  Forwarded to each PinnedToolWidget as ``layout`` so interactive iframes
   *  receive ``window.spindrel.layout``. */
  widgetLayout: WidgetLayout;
}

export function WidgetRailSection({
  channelId,
  pins,
  preset,
  chrome,
  editable = false,
  onUnpin,
  onEnvelopeUpdate,
  applyLayout,
  widgetLayout,
}: WidgetRailSectionProps) {
  // Debounced commit — reused for both resize (height change) and reorder
  // (y-order change). Uses each pin's stored dashboard x/w so the dashboard's
  // multi-column layout is preserved when the rail writes back. y comes from
  // RGL's compacted layout — in a single-column grid with compactType:vertical,
  // y is already the sequential stacking coordinate.
  const pendingTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    },
    [],
  );
  const pinsRef = useRef(pins);
  pinsRef.current = pins;

  const scheduleCommit = useCallback(
    (layout: Layout) => {
      if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
      pendingTimer.current = window.setTimeout(() => {
        const byId = new Map(pinsRef.current.map((p) => [p.id, p]));
        const updates: Array<{ id: string; x: number; y: number; w: number; h: number }> = [];
        for (const item of layout) {
          const pin = byId.get(item.i);
          if (!pin) continue;
          const gl = pin.grid_layout as GridLayoutItem | undefined;
          const origX = gl?.x ?? 0;
          const origW = Math.max(1, gl?.w ?? 1);
          updates.push({
            id: item.i,
            x: origX,
            y: item.y,
            w: origW,
            h: item.h,
          });
        }
        if (updates.length === 0) return;
        void applyLayout(updates).catch((err) => {
          console.error("Failed to persist rail layout:", err);
        });
      }, 400);
    },
    [applyLayout],
  );

  const layout: LayoutItem[] = useMemo(() => {
    let y = 0;
    return pins.map((pin) => {
      const gl = pin.grid_layout as GridLayoutItem | undefined;
      const h = Math.max(2, gl?.h ?? preset.defaultTile.h);
      const item: LayoutItem = {
        i: pin.id,
        x: 0,
        y,
        w: 1,
        h,
        minW: 1,
        maxW: 1,
        minH: 2,
      };
      y += h;
      return item;
    });
  }, [pins, preset]);

  // Single-column RGL grid. Drag via hover-revealed `.widget-drag-handle`
  // (supplied by PinnedToolWidget's railMode), resize via the south handle.
  // Width is locked (minW=maxW=1) — size on the dashboard grid is the source
  // of truth for horizontal span; here we only tweak h + y. Commit is gated
  // on explicit drag/resize stop so the initial mount's layout callback
  // doesn't overwrite the dashboard's saved y values.
  return (
    <div className="w-full omni-panel-grid">
      <ResponsiveGridLayout
        layouts={{ lg: layout }}
        breakpoints={RAIL_BREAKPOINTS}
        cols={{ lg: 1 }}
        rowHeight={preset.rowHeight}
        margin={RAIL_MARGIN}
        containerPadding={RAIL_CONTAINER_PADDING}
        isDraggable={editable}
        isResizable={editable}
        draggableHandle=".widget-drag-handle"
        resizeHandles={["s"]}
        compactType="vertical"
        preventCollision={false}
        onDragStop={(current) => {
          if (editable) scheduleCommit(current);
        }}
        onResizeStop={(current) => {
          if (editable) scheduleCommit(current);
        }}
      >
        {pins.map((pin) => (
          <div key={pin.id} data-pin-id={pin.id} className="min-w-0">
            <PinnedToolWidget
              widget={asPinnedWidget(pin)}
              scope={{ kind: "dashboard", channelId }}
              onUnpin={onUnpin}
              onEnvelopeUpdate={onEnvelopeUpdate}
              borderless={chrome.borderless}
              hoverScrollbars={chrome.hoverScrollbars}
              hideTitles={chrome.hideTitles}
              panelSurface
              railMode
              runtimeRail
              layout={widgetLayout}
            />
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
}
