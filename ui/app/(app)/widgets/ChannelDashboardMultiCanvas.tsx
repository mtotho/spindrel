/**
 * ChannelDashboardMultiCanvas — four canvases, ONE Canvas primitive.
 *
 * Every canvas (Header / Rail / Grid / Dock) uses the same `Canvas`
 * component — same RGL config, same compactType, same resize handles where
 * meaningful, same drag/drop wiring. Zone-specific differences are pure
 * data: column count, row height, optional w/h clamps, tile scope. There
 * is no "custom implementation per drop area."
 *
 * Layout source of truth: every tile's `grid_layout.{x,y,w,h}` on the pin
 * row. We do not re-stack or re-compute positions client-side — if the
 * user drags a rail widget to y=40, that's where it stays. `compactType`
 * is always `null` so drop coords persist exactly.
 *
 * Cross-canvas drag: the ZoneChip button is HTML5-draggable in edit mode
 * (`dragstart` fires a pin id into `dataTransfer`). Each canvas's
 * EditOutline wrapper is a drop target and commits via the same
 * `onMoveZone` path the dropdown uses. The widget-drag-handle inside each
 * tile continues to drive intra-canvas RGL drag via mousedown — two
 * non-conflicting event pipelines.
 *
 * IMPORTANT: do NOT add `position: relative` (or any class that could
 * override RGL's `position: absolute`) to the direct RGL child divs.
 * That is what breaks drag/resize math.
 */
import { useCallback, useMemo, useState } from "react";
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
  WidgetScope,
} from "@/src/types/api";
import type { GridPreset, DashboardChrome } from "@/src/lib/dashboardGrid";
import { EditModeGridGuides } from "./EditModeGridGuides";
import { PIN_DND_MIME } from "./ZoneChip";

const ResponsiveGridLayout = WidthProvider(Responsive);

const RAIL_CLASSES = "w-full lg:w-[280px] lg:shrink-0 order-2 lg:order-none";
const DOCK_CLASSES = "w-full lg:w-[320px] lg:shrink-0 order-3 lg:order-none";
const GRID_CLASSES = "flex-1 min-w-0 order-1 lg:order-none";
const HEADER_CLASSES = "w-full";

type ResizeHandle = "s" | "w" | "e" | "n" | "sw" | "nw" | "se" | "ne";

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

/** Drop-aware outline shown around each canvas in edit mode. */
function EditOutline({
  editMode,
  label,
  children,
  extraClass = "",
  zone,
  dragPinId = null,
  onDropTo,
}: {
  editMode: boolean;
  label: string;
  children: React.ReactNode;
  extraClass?: string;
  zone?: ChatZone;
  dragPinId?: string | null;
  onDropTo?: (pinId: string, zone: ChatZone) => void;
}) {
  const t = useThemeTokens();
  const [dragOver, setDragOver] = useState(false);

  if (!editMode) {
    return <div className={extraClass}>{children}</div>;
  }

  const dropHandlers = zone && onDropTo
    ? {
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
          const rel = e.relatedTarget as Node | null;
          if (rel && e.currentTarget.contains(rel)) return;
          setDragOver(false);
        },
        onDrop: (e: React.DragEvent) => {
          const id =
            e.dataTransfer.getData(PIN_DND_MIME) ||
            e.dataTransfer.getData("text/plain") ||
            dragPinId;
          setDragOver(false);
          if (!id) return;
          e.preventDefault();
          onDropTo(id, zone);
        },
      }
    : {};

  const borderColor = dragOver ? t.accent : `${t.textDim}33`;
  const boxShadow = dragOver ? `inset 0 0 0 2px ${t.accent}55` : undefined;

  return (
    <div
      {...dropHandlers}
      className={`relative rounded border border-dashed ${extraClass}`}
      style={{
        borderColor,
        boxShadow,
        transition: "border-color 120ms, box-shadow 120ms",
      }}
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

/** Per-canvas configuration — the ONLY place zone-specific numbers live. */
interface CanvasConfig {
  zone: ChatZone;
  label: string;
  cols: number;
  rowHeight: number;
  /** Tailwind width/order classes for the canvas wrapper. */
  extraClass: string;
  /** Resize handles available on tiles in this canvas. */
  resizeHandles: ResizeHandle[];
  /** Empty-state copy for edit mode. */
  emptyMessage: string;
  /** Scope passed to PinnedToolWidget for this canvas. */
  scope: (p: WidgetDashboardPin) => WidgetScope;
  /** Force widget to the compact rail style (hover-only chrome). */
  railMode?: boolean;
  /** Clamp every tile to this width (Rail/Dock are 1-col → 1). */
  clampW?: number;
  /** Clamp every tile to this height (Header is a 1-row chip strip → 1). */
  clampH?: number;
  /** Default tile size for pins without stored layout. */
  defaultTile: { w: number; h: number };
}

interface CanvasProps {
  pins: WidgetDashboardPin[];
  editMode: boolean;
  chrome: DashboardChrome;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
  onMoveZone: (id: string, zone: ChatZone) => void;
  dragPinId: string | null;
  onDragStartPin: (id: string) => void;
  onDragEndPin: () => void;
  config: CanvasConfig;
}

function Canvas({
  pins, editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin, onMoveZone,
  dragPinId, onDragStartPin, onDragEndPin, config,
}: CanvasProps) {
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);

  const layout: LayoutItem[] = useMemo(
    () => pins.map((p, idx) => {
      const gl = p.grid_layout as GridLayoutItem | undefined;
      const dw = config.defaultTile.w;
      const dh = config.defaultTile.h;
      const x = typeof gl?.x === "number" ? gl.x : (idx % 2) * dw;
      const y = typeof gl?.y === "number" ? gl.y : Math.floor(idx / 2) * dh;
      const w = config.clampW ?? (typeof gl?.w === "number" ? gl.w : dw);
      const h = config.clampH ?? Math.max(2, typeof gl?.h === "number" ? gl.h : dh);
      const item: LayoutItem = {
        i: p.id,
        x,
        y,
        w,
        h,
        minW: config.clampW,
        maxW: config.clampW ?? config.cols,
        minH: config.clampH ?? 2,
        maxH: config.clampH,
      };
      return item;
    }),
    [pins, config],
  );

  const rowCount = useMemo(
    () => layout.reduce((acc, it) => Math.max(acc, it.y + it.h), 0),
    [layout],
  );

  const onStop = useCallback(
    (current: Layout) => {
      void applyLayout(
        current.map((it) => ({
          id: it.i,
          x: it.x,
          y: it.y,
          w: config.clampW ?? it.w,
          h: config.clampH ?? it.h,
        })),
      );
    },
    [applyLayout, config.clampW, config.clampH],
  );

  if (!editMode && pins.length === 0) return null;

  return (
    <EditOutline
      editMode={editMode}
      label={config.label}
      extraClass={config.extraClass}
      zone={config.zone}
      dragPinId={dragPinId}
      onDropTo={(id, z) => { onMoveZone(id, z); onDragEndPin(); }}
    >
      {pins.length === 0 ? (
        editMode ? <EmptyCanvasHint message={config.emptyMessage} /> : null
      ) : (
        <div className="relative">
          {editMode && (
            <EditModeGridGuides
              cols={config.cols}
              rowHeight={config.rowHeight}
              rowGap={12}
              gridRowCount={Math.max(rowCount + 6, 24)}
              dragging={false}
            />
          )}
          <ResponsiveGridLayout
            className={editMode ? "rgl-edit-mode" : ""}
            layouts={{ lg: layout }}
            breakpoints={{ lg: 0 }}
            cols={{ lg: config.cols }}
            rowHeight={config.rowHeight}
            margin={[12, 12]}
            isDraggable={editMode}
            isResizable={editMode}
            draggableHandle=".widget-drag-handle"
            resizeHandles={config.resizeHandles}
            compactType={null}
            preventCollision={false}
            onDragStop={onStop}
            onResizeStop={onStop}
          >
            {pins.map((p) => (
              <div key={p.id} data-pin-id={p.id} className="min-w-0">
                <PinnedToolWidget
                  widget={asPinnedWidget(p)}
                  scope={config.scope(p)}
                  onUnpin={onUnpin}
                  onEnvelopeUpdate={onEnvelopeUpdate}
                  editMode={editMode}
                  onEdit={() => onEditPin(p.id)}
                  borderless={chrome.borderless}
                  hoverScrollbars={chrome.hoverScrollbars}
                  railMode={config.railMode}
                  zoneChip={editMode ? {
                    current: config.zone,
                    onSelect: (z) => onMoveZone(p.id, z),
                    pinId: p.id,
                    onDragStart: onDragStartPin,
                    onDragEnd: onDragEndPin,
                  } : undefined}
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
  const [dragPinId, setDragPinId] = useState<string | null>(null);
  const onDragStartPin = useCallback((id: string) => setDragPinId(id), []);
  const onDragEndPin = useCallback(() => setDragPinId(null), []);

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

  const headerConfig: CanvasConfig = {
    zone: "header",
    label: "Header",
    cols: 12,
    rowHeight: 32,
    extraClass: HEADER_CLASSES,
    resizeHandles: ["e"],
    emptyMessage: "Drop widgets here to show as compact chips above the channel chat.",
    scope: (p) => ({ kind: "channel", channelId: p.source_channel_id ?? "", compact: "chip" }),
    clampH: 1,
    defaultTile: { w: 1, h: 1 },
  };

  const railConfig: CanvasConfig = {
    zone: "rail",
    label: "Rail",
    cols: 1,
    rowHeight: 30,
    extraClass: RAIL_CLASSES,
    resizeHandles: ["s"],
    emptyMessage: "Drop here to pin in the chat sidebar.",
    scope: () => ({ kind: "dashboard" }),
    railMode: true,
    clampW: 1,
    defaultTile: { w: 1, h: 6 },
  };

  const dockConfig: CanvasConfig = {
    zone: "dock",
    label: "Dock",
    cols: 1,
    rowHeight: 30,
    extraClass: DOCK_CLASSES,
    resizeHandles: ["s"],
    emptyMessage: "Drop here to pin in the right-side dock.",
    scope: () => ({ kind: "dashboard" }),
    railMode: true,
    clampW: 1,
    defaultTile: { w: 1, h: 6 },
  };

  const gridConfig: CanvasConfig = {
    zone: "grid",
    label: "Grid",
    cols: preset.cols.lg,
    rowHeight: preset.rowHeight,
    extraClass: GRID_CLASSES,
    resizeHandles: ["se", "s", "e"],
    emptyMessage: "Drop widgets here to keep them on this dashboard page without surfacing them on chat.",
    scope: () => ({ kind: "dashboard" }),
    defaultTile: { w: preset.defaultTile.w, h: preset.defaultTile.h },
  };

  const canvasCommon = {
    editMode, chrome, onUnpin, onEnvelopeUpdate, onEditPin,
    onMoveZone: handleMoveZone,
    dragPinId,
    onDragStartPin,
    onDragEndPin,
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
      <Canvas pins={headerPins} config={headerConfig} {...canvasCommon} />
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-3">
        <Canvas pins={railPins} config={railConfig} {...canvasCommon} />
        <Canvas pins={gridPins} config={gridConfig} {...canvasCommon} />
        <Canvas pins={dockPins} config={dockConfig} {...canvasCommon} />
      </div>
    </div>
  );
}
