/**
 * ChannelDashboardMultiCanvas — four-canvas authoring surface for channel
 * dashboards. Each canvas maps 1:1 to a chat-side render surface:
 *
 *   Header Row   — full-width chip strip (zone: 'header')
 *   Rail          — fixed-width left column      (zone: 'rail')
 *   Main Grid     — flex-1 multi-column RGL       (zone: 'grid')  [dashboard-only]
 *   Dock          — fixed-width right column     (zone: 'dock')
 *
 * A pin's ``zone`` is stored on the row; this component filters the global
 * pin list per canvas. Intra-canvas drag and resize are driven by each
 * ResponsiveGridLayout's `.widget-drag-handle` / resize handles — we do NOT
 * override the child's `position` (RGL sets `position: absolute` on tiles
 * and any Tailwind `relative` applied here will break the drag math).
 *
 * Cross-canvas moves go through the ZoneChip dropdown in the tile header.
 *
 * Chrome: edit mode draws faint dashed outlines around each canvas with a
 * tiny corner label — no opaque header bars. View mode collapses to bare
 * widgets so the dashboard reads as one fluid page.
 */
import { useCallback, useMemo, useState, useRef, useEffect } from "react";
import {
  Responsive,
  WidthProvider,
  type Layout,
  type LayoutItem,
} from "react-grid-layout/legacy";
import "react-grid-layout/css/styles.css";
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
import { EditModeGridGuides } from "./EditModeGridGuides";

const ResponsiveGridLayout = WidthProvider(Responsive);

const RAIL_CLASSES = "w-full lg:w-[280px] lg:shrink-0";
const DOCK_CLASSES = "w-full lg:w-[320px] lg:shrink-0";
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

/** Edit-mode affordance: a very thin dashed outline wrapper with a tiny
 *  floating corner label. No opaque bars, no rounded headers, no count
 *  bubbles. In view mode the outline + label disappear entirely. */
function EditOutline({
  editMode,
  label,
  children,
  extraClass = "",
}: {
  editMode: boolean;
  label: string;
  children: React.ReactNode;
  extraClass?: string;
}) {
  const t = useThemeTokens();
  if (!editMode) {
    return <div className={extraClass}>{children}</div>;
  }
  return (
    <div
      className={`relative rounded border border-dashed ${extraClass}`}
      style={{ borderColor: `${t.textDim}33` }}
    >
      <span
        className="absolute -top-2 left-2 z-10 px-1 text-[9px] uppercase tracking-wider opacity-60 select-none pointer-events-none"
        style={{ color: t.textDim, backgroundColor: t.surface }}
      >
        {label}
      </span>
      {children}
    </div>
  );
}

/** Empty-canvas hint — tiny faint text centered in the outline, edit mode
 *  only. View mode hides the whole canvas via a null return in the parent. */
function EmptyCanvasHint({ message }: { message: string }) {
  const t = useThemeTokens();
  return (
    <div
      className="flex items-center justify-center py-4 px-3 text-[10px] text-center opacity-40 select-none"
      style={{ color: t.textDim }}
    >
      {message}
    </div>
  );
}

function HeaderCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
}: CanvasProps) {
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

  if (!editMode && pins.length === 0) return null;

  return (
    <EditOutline editMode={editMode} label="Header">
      {pins.length === 0 ? (
        editMode ? (
          <EmptyCanvasHint message="Drop widgets here to show as compact chips above the channel chat." />
        ) : null
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
    </EditOutline>
  );
}

function VerticalCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
  zone, label, widthClass, emptyMessage,
}: CanvasProps & {
  zone: "rail" | "dock";
  label: string;
  widthClass: string;
  emptyMessage: string;
}) {
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

  const rowCount = useMemo(
    () => layout.reduce((acc, it) => Math.max(acc, it.y + it.h), 0),
    [layout],
  );

  const onStop = useCallback(
    (current: Layout) => {
      void applyLayout(
        current.map((it) => ({ id: it.i, x: 0, y: it.y, w: 1, h: it.h })),
      );
    },
    [applyLayout],
  );

  if (!editMode && pins.length === 0) return null;

  const rowHeight = zone === "rail" ? RAIL_ROW_HEIGHT : DOCK_ROW_HEIGHT;

  return (
    <EditOutline editMode={editMode} label={label} extraClass={widthClass}>
      {pins.length === 0 ? (
        editMode ? <EmptyCanvasHint message={emptyMessage} /> : null
      ) : editMode ? (
        <div className="relative">
          <EditModeGridGuides
            cols={1}
            rowHeight={rowHeight}
            rowGap={12}
            gridRowCount={Math.max(rowCount, 8)}
            dragging={false}
          />
          <ResponsiveGridLayout
            layouts={{ lg: layout }}
            breakpoints={{ lg: 0 }}
            cols={{ lg: 1 }}
            rowHeight={rowHeight}
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
        </div>
      ) : (
        <ResponsiveGridLayout
          layouts={{ lg: layout }}
          breakpoints={{ lg: 0 }}
          cols={{ lg: 1 }}
          rowHeight={rowHeight}
          margin={[0, 12]}
          isDraggable={false}
          isResizable={false}
          compactType="vertical"
          preventCollision={false}
        >
          {pins.map((p) => (
            <div key={p.id} data-pin-id={p.id} className="min-w-0">
              <PinnedToolWidget
                widget={asPinnedWidget(p)}
                scope={{ kind: "dashboard" }}
                onUnpin={onUnpin}
                onEnvelopeUpdate={onEnvelopeUpdate}
                editMode={false}
                onEdit={() => onEditPin(p.id)}
                borderless={chrome.borderless}
                hoverScrollbars={chrome.hoverScrollbars}
                railMode
              />
            </div>
          ))}
        </ResponsiveGridLayout>
      )}
    </EditOutline>
  );
}

function GridCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone, preset,
}: CanvasProps & { preset: GridPreset }) {
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

  const rowCount = useMemo(
    () => layouts.lg.reduce((acc, it) => Math.max(acc, it.y + it.h), 0),
    [layouts.lg],
  );

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

  if (!editMode && pins.length === 0) return null;

  return (
    <EditOutline editMode={editMode} label="Grid" extraClass="flex-1 min-w-0">
      {pins.length === 0 ? (
        editMode ? (
          <EmptyCanvasHint message="Drop widgets here to keep them on this dashboard page without surfacing them on chat." />
        ) : null
      ) : (
        <div className="relative">
          {editMode && (
            <EditModeGridGuides
              cols={preset.cols.lg}
              rowHeight={preset.rowHeight}
              rowGap={12}
              gridRowCount={Math.max(rowCount, 8)}
              dragging={false}
            />
          )}
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
        </div>
      )}
    </EditOutline>
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
      const pin = pins.find((p) => p.id === pinId);
      if (pin && pin.zone === zone) return;
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
    [applyLayout, pins, preset.defaultTile],
  );

  const canvasCommon = {
    editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin,
    onMoveZone: handleMoveZone,
  };

  return (
    <div className="flex flex-col gap-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
        >
          {error}
        </div>
      )}
      <HeaderCanvas pins={headerPins} {...canvasCommon} />
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-3">
        <VerticalCanvas
          pins={railPins}
          {...canvasCommon}
          zone="rail"
          label="Rail"
          widthClass={RAIL_CLASSES}
          emptyMessage="Drop here to pin in the chat sidebar."
        />
        <GridCanvas pins={gridPins} preset={preset} {...canvasCommon} />
        <VerticalCanvas
          pins={dockPins}
          {...canvasCommon}
          zone="dock"
          label="Dock"
          widthClass={DOCK_CLASSES}
          emptyMessage="Drop here to pin in the right-side dock."
        />
      </div>
    </div>
  );
}
