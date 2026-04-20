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
 * ResponsiveGridLayout natively. Cross-canvas moves happen two ways:
 *   (a) HTML5 drag — each tile exposes a small "move between canvases"
 *       grip in edit mode; canvas bodies act as drop targets.
 *   (b) Zone-chip dropdown on the tile header (accessibility fallback).
 *
 * Edit vs view chrome: the canvas labels / borders / empty-state hints
 * only render while editing. In view mode the four canvases collapse to
 * a single fluid dashboard — no region chrome, no empty placeholders.
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
import { EditModeGridGuides } from "./EditModeGridGuides";

const ResponsiveGridLayout = WidthProvider(Responsive);

/** Tailwind width classes per vertical canvas. Below the `lg` breakpoint
 *  (<1024px) each canvas becomes full width and the three-column layout
 *  stacks vertically — see the outer flex container's `flex-col lg:flex-row`
 *  switch. Using classes (not inline `style.width`) so the responsive
 *  breakpoint wins over a fixed pixel value. */
const RAIL_CLASSES = "w-full lg:w-[280px] lg:shrink-0";
const DOCK_CLASSES = "w-full lg:w-[320px] lg:shrink-0";
const HEADER_COLS = 12;
const HEADER_ROW_HEIGHT = 32;
const RAIL_ROW_HEIGHT = 30;
const DOCK_ROW_HEIGHT = 30;
const DND_MIME = "application/x-spindrel-pin";

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
  /** id of a pin currently being dragged between canvases (HTML5 drag).
   *  null when no cross-canvas drag is active. */
  dragPinId: string | null;
  onDragStartPin: (id: string) => void;
  onDragEndPin: () => void;
}

/** A thin, persistent label on top of each canvas so the authoring surface
 *  is self-describing — users can always see which region they're editing
 *  without reading documentation. Only rendered in edit mode. */
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

/** Empty-canvas hint — shown only in edit mode. Without this, empty canvases
 *  look like bugs during authoring. In view mode the canvas is hidden outright. */
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

/** Per-tile wrapper. Cross-canvas drag is handled inside PinnedToolWidget via
 *  the `crossCanvasDrag` prop — that renders a grip in the tile header that
 *  emits HTML5 dragstart/dragend. We just style the outer div so the
 *  currently-dragged tile is visually highlighted as the drag source. */
function TileWrapper({
  pin,
  children,
  highlight,
}: {
  pin: WidgetDashboardPin;
  children: React.ReactNode;
  highlight?: boolean;
}) {
  const t = useThemeTokens();
  return (
    <div
      data-pin-id={pin.id}
      className="group relative min-w-0 h-full"
      style={
        highlight
          ? { outline: `2px dashed ${t.accent}`, outlineOffset: "2px", borderRadius: 8 }
          : undefined
      }
    >
      {children}
    </div>
  );
}

/** Shared drop-target handlers for a canvas body. */
function useCanvasDropHandlers(
  zone: ChatZone,
  editMode: boolean,
  dragPinId: string | null,
  onMoveZone: (id: string, zone: ChatZone) => void,
  onDragEndPin: () => void,
) {
  const [dragOver, setDragOver] = useState(false);
  const handlers = useMemo(() => {
    if (!editMode) return {};
    return {
      onDragOver: (e: React.DragEvent) => {
        if (!dragPinId) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDragOver(true);
      },
      onDragEnter: (e: React.DragEvent) => {
        if (!dragPinId) return;
        e.preventDefault();
        setDragOver(true);
      },
      onDragLeave: (e: React.DragEvent) => {
        // Only clear when leaving the element itself, not when crossing into
        // a child. `currentTarget.contains(relatedTarget)` filters children.
        const rel = e.relatedTarget as Node | null;
        if (rel && e.currentTarget.contains(rel)) return;
        setDragOver(false);
      },
      onDrop: (e: React.DragEvent) => {
        const id = e.dataTransfer.getData(DND_MIME) || dragPinId;
        setDragOver(false);
        if (!id) return;
        e.preventDefault();
        onMoveZone(id, zone);
        onDragEndPin();
      },
    };
  }, [dragPinId, editMode, onDragEndPin, onMoveZone, zone]);
  return { dragOver, handlers };
}

/** Header-row canvas. One fixed chip-height row; each pin forced to ``h=1``
 *  and rendered in compact chip mode. */
function HeaderCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
  dragPinId, onDragStartPin, onDragEndPin,
}: CanvasProps) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const { dragOver, handlers } = useCanvasDropHandlers(
    "header", editMode, dragPinId, onMoveZone, onDragEndPin,
  );

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

  // View mode with no pins: render nothing.
  if (!editMode && pins.length === 0) return null;

  const wrapperClass = editMode
    ? "flex flex-col rounded-md border"
    : "flex flex-col";
  const wrapperStyle = editMode
    ? {
        borderColor: dragOver ? t.accent : `${t.surfaceBorder}55`,
        backgroundColor: t.surface,
        boxShadow: dragOver ? `inset 0 0 0 2px ${t.accent}55` : undefined,
      }
    : {};

  return (
    <div className={wrapperClass} style={wrapperStyle} {...handlers}>
      {editMode && (
        <CanvasLabel
          icon={<PanelTop size={12} />}
          label="Chat header row"
          count={pins.length}
          description="Compact chips above the channel chat, left-to-right."
        />
      )}
      <div className={editMode ? "relative min-h-[48px]" : "relative"}>
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
              <TileWrapper
                key={p.id}
                pin={p}
                highlight={dragPinId === p.id}
              >
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
                  crossCanvasDrag={editMode ? { pinId: p.id, onStart: onDragStartPin, onEnd: onDragEndPin } : undefined}
                />
              </TileWrapper>
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
  dragPinId, onDragStartPin, onDragEndPin,
  zone, label, icon, description, widthClass, emptyMessage,
}: CanvasProps & {
  zone: "rail" | "dock";
  label: string;
  icon: React.ReactNode;
  description: string;
  /** Tailwind responsive width class (full width on narrow, fixed px on `lg`). */
  widthClass: string;
  emptyMessage: string;
}) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const { dragOver, handlers } = useCanvasDropHandlers(
    zone, editMode, dragPinId, onMoveZone, onDragEndPin,
  );

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
  const wrapperClass = editMode
    ? `flex flex-col rounded-md border ${widthClass}`
    : `flex flex-col ${widthClass}`;
  const wrapperStyle = editMode
    ? {
        borderColor: dragOver ? t.accent : `${t.surfaceBorder}55`,
        backgroundColor: t.surface,
        boxShadow: dragOver ? `inset 0 0 0 2px ${t.accent}55` : undefined,
      }
    : {};

  return (
    <div className={wrapperClass} style={wrapperStyle} {...handlers}>
      {editMode && (
        <CanvasLabel icon={icon} label={label} count={pins.length} description={description} />
      )}
      <div className={editMode ? "flex-1 min-h-0 overflow-y-auto px-2 py-2" : "flex-1 min-h-0 overflow-y-auto"}>
        {pins.length === 0 ? (
          editMode ? <EmptyCanvasHint message={emptyMessage} /> : null
        ) : (
          <div className="relative">
            {editMode && (
              <EditModeGridGuides
                cols={1}
                rowHeight={rowHeight}
                rowGap={12}
                gridRowCount={Math.max(rowCount, 8)}
                dragging={!!dragPinId}
              />
            )}
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
                <TileWrapper
                  key={p.id}
                  pin={p}
                  highlight={dragPinId === p.id}
                >
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
                    crossCanvasDrag={editMode ? { pinId: p.id, onStart: onDragStartPin, onEnd: onDragEndPin } : undefined}
                  />
                </TileWrapper>
              ))}
            </ResponsiveGridLayout>
          </div>
        )}
      </div>
    </div>
  );
}

/** Main-grid canvas — the dashboard-only surface. Uses the full preset. */
function GridCanvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
  dragPinId, onDragStartPin, onDragEndPin, preset,
}: CanvasProps & { preset: GridPreset }) {
  const t = useThemeTokens();
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const { dragOver, handlers } = useCanvasDropHandlers(
    "grid", editMode, dragPinId, onMoveZone, onDragEndPin,
  );

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

  const wrapperClass = editMode
    ? "flex-1 flex flex-col rounded-md border min-w-0"
    : "flex-1 flex flex-col min-w-0";
  const wrapperStyle = editMode
    ? {
        borderColor: dragOver ? t.accent : `${t.surfaceBorder}55`,
        backgroundColor: t.surface,
        boxShadow: dragOver ? `inset 0 0 0 2px ${t.accent}55` : undefined,
      }
    : {};

  return (
    <div className={wrapperClass} style={wrapperStyle} {...handlers}>
      {editMode && (
        <CanvasLabel
          icon={<LayoutDashboard size={12} />}
          label="Main grid · dashboard only"
          count={pins.length}
          description="Widgets here are authoring-surface only — they do NOT appear on the channel chat."
        />
      )}
      <div className={editMode ? "flex-1 min-h-0 overflow-auto px-2 py-2" : "flex-1 min-h-0 overflow-auto"}>
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
                dragging={!!dragPinId}
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
                <TileWrapper
                  key={p.id}
                  pin={p}
                  highlight={dragPinId === p.id}
                >
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
                    crossCanvasDrag={editMode ? { pinId: p.id, onStart: onDragStartPin, onEnd: onDragEndPin } : undefined}
                  />
                </TileWrapper>
              ))}
            </ResponsiveGridLayout>
          </div>
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
  const [dragPinId, setDragPinId] = useState<string | null>(null);

  const railPins = useMemo(() => pins.filter((p) => p.zone === "rail"), [pins]);
  const headerPins = useMemo(() => pins.filter((p) => p.zone === "header"), [pins]);
  const dockPins = useMemo(() => pins.filter((p) => p.zone === "dock"), [pins]);
  const gridPins = useMemo(() => pins.filter((p) => p.zone === "grid"), [pins]);

  const handleMoveZone = useCallback(
    async (pinId: string, zone: ChatZone) => {
      const pin = pins.find((p) => p.id === pinId);
      if (pin && pin.zone === zone) return;
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
    [applyLayout, pins, preset.defaultTile],
  );

  const handleDragStartPin = useCallback((id: string) => setDragPinId(id), []);
  const handleDragEndPin = useCallback(() => setDragPinId(null), []);

  const canvasCommon = {
    editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin,
    onMoveZone: handleMoveZone,
    dragPinId,
    onDragStartPin: handleDragStartPin,
    onDragEndPin: handleDragEndPin,
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
      <div
        className={
          "flex flex-col gap-3 lg:flex-row " +
          (editMode ? "lg:min-h-[320px]" : "")
        }
      >
        <VerticalCanvas
          pins={railPins}
          {...canvasCommon}
          zone="rail"
          label="Chat sidebar rail"
          icon={<PanelLeft size={12} />}
          description="Widgets in the OmniPanel rail on the left side of the channel chat."
          widthClass={RAIL_CLASSES}
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
          widthClass={DOCK_CLASSES}
          emptyMessage="Drop widgets here to pin them on the right side of the channel chat."
        />
      </div>
    </div>
  );
}
