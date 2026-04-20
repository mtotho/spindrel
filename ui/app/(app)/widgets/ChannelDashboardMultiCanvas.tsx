/**
 * ChannelDashboardMultiCanvas — four-canvas authoring surface for channel
 * dashboards. Each canvas maps 1:1 to a chat-side render surface:
 *
 *   Header Row   — full-width chip strip (zone: 'header')
 *   Rail          — fixed-width left column      (zone: 'rail')
 *   Main Grid     — flex-1 multi-column RGL       (zone: 'grid')  [dashboard-only]
 *   Dock          — fixed-width right column     (zone: 'dock')
 *
 * A pin's ``zone`` is stored on the row; this component just filters the
 * global pin list per canvas. Intra-canvas drag is handled by each
 * ResponsiveGridLayout natively. Cross-canvas moves use the per-tile zone
 * picker (the chip button at the top of each tile in edit mode) which calls
 * ``applyLayout`` with a ``zone`` plus fresh canvas-local coords.
 */
import { useCallback, useMemo, useState, useRef, useEffect } from "react";
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
import { ArrowRight, LayoutDashboard, PanelLeft, PanelTop } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import type {
  ChatZone,
  GridLayoutItem,
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import type { GridPreset, DashboardChrome } from "@/src/lib/dashboardGrid";

const ResponsiveGridLayout = WidthProvider(Responsive);

const RAIL_WIDTH = 280;
const DOCK_WIDTH = 320;
const HEADER_COLS = 12;
const HEADER_ROW_HEIGHT = 32;
const RAIL_ROW_HEIGHT = 30;
const DOCK_ROW_HEIGHT = 30;

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    config: pin.widget_config ?? {},
  };
}

interface CanvasProps {
  pins: WidgetDashboardPin[];
  editMode: boolean;
  chrome: DashboardChrome;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
  onMoveZone: (id: string, zone: ChatZone) => void;
}

/** A thin, persistent label on top of each canvas so the authoring surface
 *  is self-describing — users can always see which region they're editing
 *  without reading documentation. */
function CanvasLabel({
  icon,
  label,
  count,
  description,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
  description: string;
}) {
  const t = useThemeTokens();
  return (
    <div
      className="flex items-center gap-1.5 px-2 py-1 rounded-t-md"
      style={{
        backgroundColor: t.surfaceRaised,
        borderBottom: `1px solid ${t.surfaceBorder}55`,
      }}
      title={description}
    >
      <span style={{ color: t.textDim }} className="flex items-center">
        {icon}
      </span>
      <span
        className="text-[10px] font-semibold uppercase tracking-wider flex-1"
        style={{ color: t.textDim }}
      >
        {label}
      </span>
      <span
        className="text-[10px] tabular-nums rounded-full px-1.5 py-0.5"
        style={{
          color: t.textMuted,
          backgroundColor: `${t.textMuted}18`,
        }}
      >
        {count}
      </span>
    </div>
  );
}

/** Empty-canvas hint — replaces a bare empty region with copy explaining
 *  what to drop into it. Critical: without this, empty canvases look like
 *  bugs. */
function EmptyCanvasHint({ message }: { message: string }) {
  const t = useThemeTokens();
  return (
    <div
      className="flex items-center justify-center py-6 px-4 text-[11px] text-center"
      style={{ color: t.textDim, opacity: 0.6 }}
    >
      {message}
    </div>
  );
}

/** Header-row canvas. One fixed chip-height row; each pin forced to ``h=1``
 *  and rendered in compact chip mode. */
function HeaderCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
}: CanvasProps) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);

  const layout: LayoutItem[] = useMemo(
    () => pins.map((p, i) => {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      return {
        i: p.id,
        x: gl?.x ?? i,
        y: 0,
        w: Math.max(1, Math.min(HEADER_COLS, gl?.w ?? 1)),
        h: 1,
        minH: 1,
        maxH: 1,
      };
    }),
    [pins],
  );

  const onDragStop = useCallback(
    (current: Layout) => {
      void applyLayout(
        current.map((it) => ({ id: it.i, x: it.x, y: 0, w: it.w, h: 1 })),
      );
    },
    [applyLayout],
  );

  return (
    <div
      className="flex flex-col rounded-md border"
      style={{ borderColor: `${t.surfaceBorder}55`, backgroundColor: t.surface }}
    >
      <CanvasLabel
        icon={<PanelTop size={12} />}
        label="Chat header row"
        count={pins.length}
        description="Compact chips above the channel chat, left-to-right."
      />
      <div className="min-h-[48px]">
        {pins.length === 0 ? (
          <EmptyCanvasHint message="Drop widgets here to show as compact chips above the channel chat." />
        ) : (
          <ResponsiveGridLayout
            layouts={{ lg: layout }}
            breakpoints={{ lg: 0 }}
            cols={{ lg: HEADER_COLS }}
            rowHeight={HEADER_ROW_HEIGHT}
            margin={[8, 8]}
            isDraggable={editMode}
            isResizable={editMode}
            draggableHandle=".widget-drag-handle"
            resizeHandles={["e"]}
            compactType="horizontal"
            preventCollision={false}
            onDragStop={onDragStop}
            onResizeStop={onDragStop}
          >
            {pins.map((p) => (
              <div key={p.id} data-pin-id={p.id} className="min-w-0">
                <PinnedToolWidget
                  widget={asPinnedWidget(p)}
                  scope={{ kind: "channel", channelId: p.source_channel_id ?? "", compact: "chip" }}
                  onUnpin={onUnpin}
                  onEnvelopeUpdate={onEnvelopeUpdate}
                  editMode={editMode}
                  onEdit={() => onEditPin(p.id)}
                  borderless={chrome.borderless}
                  hoverScrollbars={chrome.hoverScrollbars}
                  zoneChip={editMode ? { current: "header", onSelect: (z) => onMoveZone(p.id, z) } : undefined}
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}

/** Single-column vertical canvas (Rail or Dock). */
function VerticalCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
  zone, label, icon, description, width, emptyMessage,
}: CanvasProps & {
  zone: "rail" | "dock";
  label: string;
  icon: React.ReactNode;
  description: string;
  width: number;
  emptyMessage: string;
}) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);

  const layout: LayoutItem[] = useMemo(() => {
    let y = 0;
    return pins.map((p) => {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      const h = Math.max(2, gl?.h ?? 6);
      const item: LayoutItem = { i: p.id, x: 0, y, w: 1, h, minW: 1, maxW: 1, minH: 2 };
      y += h;
      return item;
    });
  }, [pins]);

  const onStop = useCallback(
    (current: Layout) => {
      void applyLayout(
        current.map((it) => ({ id: it.i, x: 0, y: it.y, w: 1, h: it.h })),
      );
    },
    [applyLayout],
  );

  return (
    <div
      className="flex flex-col rounded-md border shrink-0"
      style={{ width, borderColor: `${t.surfaceBorder}55`, backgroundColor: t.surface }}
    >
      <CanvasLabel icon={icon} label={label} count={pins.length} description={description} />
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2">
        {pins.length === 0 ? (
          <EmptyCanvasHint message={emptyMessage} />
        ) : (
          <ResponsiveGridLayout
            layouts={{ lg: layout }}
            breakpoints={{ lg: 0 }}
            cols={{ lg: 1 }}
            rowHeight={zone === "rail" ? RAIL_ROW_HEIGHT : DOCK_ROW_HEIGHT}
            margin={[0, 12]}
            isDraggable={editMode}
            isResizable={editMode}
            draggableHandle=".widget-drag-handle"
            resizeHandles={["s"]}
            compactType="vertical"
            preventCollision={false}
            onDragStop={onStop}
            onResizeStop={onStop}
          >
            {pins.map((p) => (
              <div key={p.id} data-pin-id={p.id} className="min-w-0">
                <PinnedToolWidget
                  widget={asPinnedWidget(p)}
                  scope={{ kind: "dashboard" }}
                  onUnpin={onUnpin}
                  onEnvelopeUpdate={onEnvelopeUpdate}
                  editMode={editMode}
                  onEdit={() => onEditPin(p.id)}
                  borderless={chrome.borderless}
                  hoverScrollbars={chrome.hoverScrollbars}
                  railMode
                  zoneChip={editMode ? { current: zone, onSelect: (z) => onMoveZone(p.id, z) } : undefined}
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}

/** Main-grid canvas — the dashboard-only surface. Uses the full preset. */
function GridCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone, preset,
}: CanvasProps & { preset: GridPreset }) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);

  const layouts = useMemo(() => {
    const lg: LayoutItem[] = pins.map((p, idx) => {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      const base = gl && typeof gl.x === "number" ? gl : {
        x: (idx % 2) * preset.defaultTile.w,
        y: Math.floor(idx / 2) * preset.defaultTile.h,
        w: preset.defaultTile.w,
        h: preset.defaultTile.h,
      };
      return {
        i: p.id,
        x: base.x,
        y: base.y,
        w: base.w,
        h: base.h,
        minW: preset.minTile.w,
        minH: preset.minTile.h,
        maxW: preset.cols.lg,
      };
    });
    return { lg };
  }, [pins, preset]);

  const pendingTimer = useRef<number | null>(null);
  useEffect(() => () => {
    if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
  }, []);

  const scheduleCommit = useCallback((current: Layout) => {
    if (pendingTimer.current) window.clearTimeout(pendingTimer.current);
    pendingTimer.current = window.setTimeout(() => {
      void applyLayout(
        current.map((it) => ({ id: it.i, x: it.x, y: it.y, w: it.w, h: it.h })),
      );
    }, 400);
  }, [applyLayout]);

  return (
    <div
      className="flex-1 flex flex-col rounded-md border min-w-0"
      style={{ borderColor: `${t.surfaceBorder}55`, backgroundColor: t.surface }}
    >
      <CanvasLabel
        icon={<LayoutDashboard size={12} />}
        label="Main grid · dashboard only"
        count={pins.length}
        description="Widgets here are authoring-surface only — they do NOT appear on the channel chat."
      />
      <div className="flex-1 min-h-0 overflow-auto px-2 py-2">
        {pins.length === 0 ? (
          <EmptyCanvasHint message="Drop widgets here to keep them on this dashboard page without surfacing them on chat." />
        ) : (
          <ResponsiveGridLayout
            layouts={layouts}
            breakpoints={{ lg: 0 }}
            cols={{ lg: preset.cols.lg }}
            rowHeight={preset.rowHeight}
            margin={[12, 12]}
            isDraggable={editMode}
            isResizable={editMode}
            draggableHandle=".widget-drag-handle"
            compactType="vertical"
            preventCollision={false}
            onLayoutChange={scheduleCommit}
          >
            {pins.map((p) => (
              <div key={p.id} data-pin-id={p.id} className="min-w-0">
                <PinnedToolWidget
                  widget={asPinnedWidget(p)}
                  scope={{ kind: "dashboard" }}
                  onUnpin={onUnpin}
                  onEnvelopeUpdate={onEnvelopeUpdate}
                  editMode={editMode}
                  onEdit={() => onEditPin(p.id)}
                  borderless={chrome.borderless}
                  hoverScrollbars={chrome.hoverScrollbars}
                  zoneChip={editMode ? { current: "grid", onSelect: (z) => onMoveZone(p.id, z) } : undefined}
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        )}
      </div>
    </div>
  );
}

interface Props {
  pins: WidgetDashboardPin[];
  preset: GridPreset;
  chrome: DashboardChrome;
  editMode: boolean;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
}

export function ChannelDashboardMultiCanvas({
  pins, preset, chrome, editMode, onUnpin, onEnvelopeUpdate, onEditPin,
}: Props) {
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const [error, setError] = useState<string | null>(null);

  const railPins = useMemo(() => pins.filter((p) => p.zone === "rail"), [pins]);
  const headerPins = useMemo(() => pins.filter((p) => p.zone === "header"), [pins]);
  const dockPins = useMemo(() => pins.filter((p) => p.zone === "dock"), [pins]);
  const gridPins = useMemo(() => pins.filter((p) => p.zone === "grid"), [pins]);

  const handleMoveZone = useCallback(
    async (pinId: string, zone: ChatZone) => {
      // Canvas-local default coords per destination.
      const defaults: Record<ChatZone, { x: number; y: number; w: number; h: number }> = {
        rail: { x: 0, y: 0, w: 1, h: 6 },
        dock: { x: 0, y: 0, w: 1, h: 6 },
        header: { x: 0, y: 0, w: 1, h: 1 },
        grid: { x: 0, y: 0, w: preset.defaultTile.w, h: preset.defaultTile.h },
      };
      try {
        await applyLayout([{ id: pinId, zone, ...defaults[zone] }]);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to move widget");
      }
    },
    [applyLayout, preset.defaultTile],
  );

  const canvasCommon = {
    editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin,
    onMoveZone: handleMoveZone,
  };

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
        >
          {error}
        </div>
      )}
      <HeaderCanvas pins={headerPins} {...canvasCommon} />
      <div className="flex gap-3 min-h-[320px]">
        <VerticalCanvas
          pins={railPins}
          {...canvasCommon}
          zone="rail"
          label="Chat sidebar rail"
          icon={<PanelLeft size={12} />}
          description="Widgets in the OmniPanel rail on the left side of the channel chat."
          width={RAIL_WIDTH}
          emptyMessage="Drop widgets here to pin them in the chat sidebar."
        />
        <GridCanvas pins={gridPins} preset={preset} {...canvasCommon} />
        <VerticalCanvas
          pins={dockPins}
          {...canvasCommon}
          zone="dock"
          label="Chat right dock"
          icon={<ArrowRight size={12} />}
          description="Widgets in the right-side dock on the channel chat."
          width={DOCK_WIDTH}
          emptyMessage="Drop widgets here to pin them on the right side of the channel chat."
        />
      </div>
    </div>
  );
}

