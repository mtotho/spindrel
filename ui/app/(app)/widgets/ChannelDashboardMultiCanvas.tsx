/**
 * ChannelDashboardMultiCanvas — four canvases, one DndContext.
 *
 * Every widget is drag-and-droppable directly by its grip icon:
 *
 *   - Within rail / header / dock (1-D lists): sortable reorder via
 *     `SortableContext`.
 *   - Within grid (2-D free placement): `useDraggable` + pointer-to-cell
 *     snap at drop time against the canvas's bounding rect.
 *   - Across any two canvases: dropping on another canvas's droppable zone
 *     issues `handleMoveZone(pinId, targetZone)` which writes the new zone
 *     + default coords atomically via `applyLayout`.
 *
 * Resize is owned by pointer-event handles on each tile (south / east /
 * south-east). No second drag pipeline; no ZoneChip.
 *
 * Layout source of truth: every pin's `grid_layout.{x,y,w,h}` on the pin
 * row plus `zone`. This component is a pure renderer of that state.
 */
import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  horizontalListSortingStrategy,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
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
import {
  DroppableCanvas,
  GridTile,
  ResizeHandles,
  SortableTile,
  pointerToCell,
  clampPlacement,
  sequentialXLayout,
  sequentialYLayout,
  useCanvasMeasure,
  type ExternalDragBinding,
  type ResizeEdge,
} from "./DashboardDnd";

const RAIL_CLASSES = "w-full lg:w-[280px] lg:shrink-0 order-2 lg:order-none";
const DOCK_CLASSES = "w-full lg:w-[320px] lg:shrink-0 order-3 lg:order-none";
const GRID_CLASSES = "flex-1 min-w-0 order-1 lg:order-none";
const HEADER_CLASSES = "w-full";

const GAP_PX = 12;

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

function toGridLayout(pin: WidgetDashboardPin): GridLayoutItem {
  const gl = pin.grid_layout as GridLayoutItem | Record<string, never>;
  if (
    typeof (gl as GridLayoutItem).x === "number"
    && typeof (gl as GridLayoutItem).y === "number"
    && typeof (gl as GridLayoutItem).w === "number"
    && typeof (gl as GridLayoutItem).h === "number"
  ) {
    return gl as GridLayoutItem;
  }
  return { x: 0, y: 0, w: 1, h: 6 };
}

interface Props {
  pins: WidgetDashboardPin[];
  preset: GridPreset;
  chrome: DashboardChrome;
  editMode: boolean;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
  /** Channel uuid parsed from the dashboard slug (``channel:<uuid>``).
   *  Plumbed into every pin's `scope.channelId` so `window.spindrel.channelId`
   *  resolves correctly for pinned HTML widgets. */
  channelId: string;
}

export function ChannelDashboardMultiCanvas({
  pins,
  preset,
  chrome,
  editMode,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  channelId,
}: Props) {
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const [error, setError] = useState<string | null>(null);
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [overZone, setOverZone] = useState<ChatZone | null>(null);

  // Sortable canvases render in grid_layout order so reorder commits (which
  // only update x or y) actually change the render position. Without the
  // sort, `arrayMove` writes new x/y into the store but the filter keeps the
  // original pin-insertion order and tiles "pop back" visually on drop. The
  // grid canvas uses CSS Grid positioning via `gridColumn`/`gridRow`, so the
  // filter order there is irrelevant.
  const railPins = useMemo(
    () =>
      pins
        .filter((p) => p.zone === "rail")
        .slice()
        .sort((a, b) => toGridLayout(a).y - toGridLayout(b).y),
    [pins],
  );
  const headerPins = useMemo(
    () =>
      pins
        .filter((p) => p.zone === "header")
        .slice()
        .sort((a, b) => toGridLayout(a).x - toGridLayout(b).x),
    [pins],
  );
  const dockPins = useMemo(
    () =>
      pins
        .filter((p) => p.zone === "dock")
        .slice()
        .sort((a, b) => toGridLayout(a).y - toGridLayout(b).y),
    [pins],
  );
  const gridPins = useMemo(() => pins.filter((p) => p.zone === "grid"), [pins]);

  // One measure ref per canvas so drop-time pointer math knows each canvas's
  // bounding rect independently (lg: row is flex-row).
  const gridMeasure = useCanvasMeasure();

  // Default tile sizes used when a cross-canvas drop needs to assign fresh
  // coords (the source canvas's x/y/w/h doesn't translate).
  const defaultForZone = useCallback(
    (zone: ChatZone): { x: number; y: number; w: number; h: number } => {
      switch (zone) {
        case "rail":
        case "dock":
          return { x: 0, y: 0, w: 1, h: 6 };
        case "header":
          return { x: 0, y: 0, w: 1, h: 1 };
        case "grid":
        default:
          return {
            x: 0,
            y: 0,
            w: preset.defaultTile.w,
            h: preset.defaultTile.h,
          };
      }
    },
    [preset.defaultTile],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const onDragStart = useCallback((e: DragStartEvent) => {
    setActiveDragId(String(e.active.id));
    setError(null);
  }, []);

  const onDragOver = useCallback((e: DragOverEvent) => {
    const overId = e.over?.id;
    if (typeof overId === "string" && overId.startsWith("canvas:")) {
      setOverZone(overId.slice("canvas:".length) as ChatZone);
      return;
    }
    // Hovering over a sibling tile: the sibling's zone is its source zone.
    if (typeof overId === "string") {
      const pin = pins.find((p) => p.id === overId);
      setOverZone(pin?.zone ?? null);
      return;
    }
    setOverZone(null);
  }, [pins]);

  const commitCrossCanvasMove = useCallback(
    async (pinId: string, targetZone: ChatZone) => {
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) return;
      if (pin.zone === targetZone) return;
      try {
        await applyLayout([{ id: pinId, zone: targetZone, ...defaultForZone(targetZone) }]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to move widget");
      }
    },
    [pins, applyLayout, defaultForZone],
  );

  const commitSortableReorder = useCallback(
    async (zone: "rail" | "dock" | "header", fromId: string, toId: string) => {
      // Match the filter/sort used by the render so arrayMove operates on the
      // same array the user sees. Otherwise the reorder index math drifts
      // from the visual order.
      const sortKey = zone === "header"
        ? (p: WidgetDashboardPin) => toGridLayout(p).x
        : (p: WidgetDashboardPin) => toGridLayout(p).y;
      const zonePins = pins
        .filter((p) => p.zone === zone)
        .slice()
        .sort((a, b) => sortKey(a) - sortKey(b));
      const ids = zonePins.map((p) => p.id);
      const from = ids.indexOf(fromId);
      const to = ids.indexOf(toId);
      if (from < 0 || to < 0 || from === to) return;
      const reordered = arrayMove(ids, from, to);
      const byId = new Map<string, GridLayoutItem>(
        zonePins.map((p) => [p.id, toGridLayout(p)]),
      );
      const nextLayout =
        zone === "header"
          ? sequentialXLayout(reordered, byId)
          : sequentialYLayout(reordered, 6, byId);
      const items = reordered.map((id) => {
        const coords = nextLayout.get(id)!;
        return { id, ...coords };
      });
      try {
        await applyLayout(items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reorder");
      }
    },
    [pins, applyLayout],
  );

  const commitGridMove = useCallback(
    async (pinId: string, clientX: number, clientY: number) => {
      const rect = gridMeasure.rect;
      if (!rect) return;
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) return;
      const existing = toGridLayout(pin);
      const cfg = {
        cols: preset.cols.lg,
        rowHeight: preset.rowHeight,
        gap: GAP_PX,
        canvasWidth: rect.width,
      };
      const { x, y } = pointerToCell(clientX - rect.left, clientY - rect.top, cfg);
      const placement = clampPlacement(x, y, existing.w, existing.h, cfg.cols);
      // No-op if the tile didn't actually move cells.
      if (
        pin.zone === "grid"
        && placement.x === existing.x
        && placement.y === existing.y
        && placement.w === existing.w
        && placement.h === existing.h
      ) {
        return;
      }
      try {
        await applyLayout([{ id: pinId, zone: "grid", ...placement }]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to place widget");
      }
    },
    [pins, applyLayout, preset.cols.lg, preset.rowHeight, gridMeasure],
  );

  const onDragEnd = useCallback(
    async (e: DragEndEvent) => {
      const activeId = String(e.active.id);
      const overId = e.over?.id != null ? String(e.over.id) : null;
      setActiveDragId(null);
      setOverZone(null);
      if (!overId) return;

      const active = pins.find((p) => p.id === activeId);
      if (!active) return;

      // Resolve the target zone: `canvas:<zone>` droppable or a sibling tile.
      let targetZone: ChatZone;
      if (overId.startsWith("canvas:")) {
        targetZone = overId.slice("canvas:".length) as ChatZone;
      } else {
        const overPin = pins.find((p) => p.id === overId);
        if (!overPin) return;
        targetZone = overPin.zone;
      }

      if (targetZone !== active.zone) {
        // Cross-canvas move — use defaults for the target zone.
        await commitCrossCanvasMove(activeId, targetZone);
        return;
      }

      // Same-zone move:
      if (targetZone === "grid") {
        // Free placement: snap pointer to a cell.
        const pe = (e.activatorEvent as PointerEvent | null);
        // Activator event holds the starting pointer; we want the release
        // point, which dnd-kit exposes via `e.delta`.
        const startX = pe?.clientX ?? 0;
        const startY = pe?.clientY ?? 0;
        await commitGridMove(
          activeId,
          startX + e.delta.x,
          startY + e.delta.y,
        );
        return;
      }

      // Sortable reorder within rail / header / dock:
      if (overId !== activeId && !overId.startsWith("canvas:")) {
        await commitSortableReorder(
          targetZone,
          activeId,
          overId,
        );
      }
    },
    [pins, commitCrossCanvasMove, commitGridMove, commitSortableReorder],
  );

  const activePin = activeDragId ? pins.find((p) => p.id === activeDragId) ?? null : null;

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      <div className="flex flex-col gap-4">
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
          >
            {error}
          </div>
        )}

        <HeaderCanvas
          pins={headerPins}
          editMode={editMode}
          chrome={chrome}
          onUnpin={onUnpin}
          onEnvelopeUpdate={onEnvelopeUpdate}
          onEditPin={onEditPin}
          anyDragging={activeDragId !== null}
          isOver={overZone === "header"}
          applyLayout={applyLayout}
          channelId={channelId}
        />

        <div className="flex flex-col gap-4 lg:flex-row lg:gap-3">
          <ListCanvas
            zone="rail"
            label="Rail"
            extraClass={RAIL_CLASSES}
            emptyMessage="Drop here to pin in the chat sidebar."
            pins={railPins}
            editMode={editMode}
            chrome={chrome}
            onUnpin={onUnpin}
            onEnvelopeUpdate={onEnvelopeUpdate}
            onEditPin={onEditPin}
            anyDragging={activeDragId !== null}
            isOver={overZone === "rail"}
            applyLayout={applyLayout}
            channelId={channelId}
          />

          <GridCanvas
            pins={gridPins}
            preset={preset}
            editMode={editMode}
            chrome={chrome}
            onUnpin={onUnpin}
            onEnvelopeUpdate={onEnvelopeUpdate}
            onEditPin={onEditPin}
            anyDragging={activeDragId !== null}
            isOver={overZone === "grid"}
            applyLayout={applyLayout}
            measureRef={gridMeasure.setRef}
            measuredRect={gridMeasure.rect}
            channelId={channelId}
          />

          <ListCanvas
            zone="dock"
            label="Dock"
            extraClass={DOCK_CLASSES}
            emptyMessage="Drop here to pin in the right-side dock."
            pins={dockPins}
            editMode={editMode}
            chrome={chrome}
            onUnpin={onUnpin}
            onEnvelopeUpdate={onEnvelopeUpdate}
            onEditPin={onEditPin}
            anyDragging={activeDragId !== null}
            isOver={overZone === "dock"}
            applyLayout={applyLayout}
            channelId={channelId}
          />
        </div>
      </div>

      <DragOverlay dropAnimation={null}>
        {activePin && (
          <div className="opacity-80 pointer-events-none">
            <PinnedToolWidget
              widget={asPinnedWidget(activePin)}
              scope={{ kind: "dashboard", channelId }}
              onUnpin={() => {}}
              onEnvelopeUpdate={() => {}}
              editMode={editMode}
              borderless={chrome.borderless}
              hoverScrollbars={chrome.hoverScrollbars}
              railMode={activePin.zone === "rail" || activePin.zone === "dock"}
            />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}

// ---------------------------------------------------------------------------
// Header canvas — horizontal sortable strip of 1x1 chips.
// ---------------------------------------------------------------------------

interface CanvasSharedProps {
  pins: WidgetDashboardPin[];
  editMode: boolean;
  chrome: DashboardChrome;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
  anyDragging: boolean;
  isOver: boolean;
  applyLayout: (items: Array<{
    id: string;
    x: number;
    y: number;
    w: number;
    h: number;
    zone?: ChatZone;
  }>) => Promise<void>;
  /** Enclosing channel dashboard's channel uuid — carried into every pin's
   *  `WidgetScope.dashboard.channelId` so `window.spindrel.channelId` resolves. */
  channelId: string;
}

function HeaderCanvas({
  pins,
  editMode,
  chrome,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  anyDragging,
  isOver,
  channelId,
}: CanvasSharedProps) {
  if (!editMode && pins.length === 0) return null;
  // Edit mode shows the full dashboard tile (grip + edit + unpin controls).
  // View mode renders each header pin as a compact chip — matches how
  // ChannelHeaderChip surfaces the same pins in the chat strip.
  const tileScope = (_p: WidgetDashboardPin): WidgetScope =>
    editMode
      ? { kind: "dashboard", channelId }
      : {
          kind: "channel",
          channelId,
          compact: "chip",
        };
  const ids = pins.map((p) => p.id);

  return (
    <DroppableCanvas
      zone="header"
      label="Header"
      extraClass={HEADER_CLASSES}
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
    >
      <div className="relative flex-1 min-h-[56px] overflow-hidden p-3">
        {editMode && <EditModeGridGuides cols={12} rowHeight={32} rowGap={GAP_PX} />}
        {pins.length === 0 ? (
          editMode ? (
            <EmptyCanvasHint message="Drop widgets here to show as compact chips above the channel chat." />
          ) : null
        ) : (
          <SortableContext items={ids} strategy={horizontalListSortingStrategy}>
            <div className="relative flex flex-row gap-2 overflow-x-auto">
              {pins.map((p) => (
                <SortableTile key={p.id} id={p.id}>
                  {(binding) => (
                    <div
                      ref={binding.setNodeRef}
                      {...binding.attributes}
                      style={binding.style}
                    >
                      <TileShell
                        binding={{ ...binding, setNodeRef: () => {} }}
                        pin={p}
                        editMode={editMode}
                        chrome={chrome}
                        scope={tileScope(p)}
                        onUnpin={onUnpin}
                        onEnvelopeUpdate={onEnvelopeUpdate}
                        onEditPin={onEditPin}
                        resize={null}
                      />
                    </div>
                  )}
                </SortableTile>
              ))}
            </div>
          </SortableContext>
        )}
      </div>
    </DroppableCanvas>
  );
}

// ---------------------------------------------------------------------------
// List canvas — used by rail + dock (vertical 1-column lists with resizable H).
// ---------------------------------------------------------------------------

interface ListCanvasProps extends CanvasSharedProps {
  zone: "rail" | "dock";
  label: string;
  extraClass: string;
  emptyMessage: string;
}

function ListCanvas({
  zone,
  label,
  extraClass,
  emptyMessage,
  pins,
  editMode,
  chrome,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  anyDragging,
  isOver,
  applyLayout,
  channelId,
}: ListCanvasProps) {
  if (!editMode && pins.length === 0) return null;
  const ids = pins.map((p) => p.id);
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });
  const rowHeight = 30;
  const [resizePreview, setResizePreview] = useState<{ id: string; h: number } | null>(null);

  return (
    <DroppableCanvas
      zone={zone}
      label={label}
      extraClass={extraClass}
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
    >
      <div className="relative flex-1 min-h-[200px] overflow-hidden p-3">
        {editMode && <EditModeGridGuides cols={1} rowHeight={rowHeight} rowGap={GAP_PX} />}
        {pins.length === 0 ? (
          editMode ? <EmptyCanvasHint message={emptyMessage} /> : null
        ) : (
          <SortableContext items={ids} strategy={verticalListSortingStrategy}>
            <div className="relative flex flex-col gap-3">
              {pins.map((p) => {
              const gl = toGridLayout(p);
              const effH =
                resizePreview?.id === p.id ? resizePreview.h : gl.h;
              const tileHeightPx = effH * (rowHeight + GAP_PX) - GAP_PX;
              return (
                <SortableTile key={p.id} id={p.id}>
                  {(binding) => (
                    <div
                      ref={binding.setNodeRef}
                      {...binding.attributes}
                      className="relative"
                      style={{
                        ...binding.style,
                        height: editMode ? tileHeightPx : undefined,
                      }}
                    >
                      <TileShell
                        binding={{ ...binding, setNodeRef: () => {} }}
                        pin={p}
                        editMode={editMode}
                        chrome={chrome}
                        scope={dashboardScope()}
                        onUnpin={onUnpin}
                        onEnvelopeUpdate={onEnvelopeUpdate}
                        onEditPin={onEditPin}
                        railMode
                        resize={
                          editMode
                            ? {
                                edges: ["s"],
                                initial: { w: 1, h: gl.h },
                                cellPx: { w: 280, h: rowHeight + GAP_PX },
                                clampW: { min: 1, max: 1 },
                                clampH: { min: 2 },
                                onResizing: ({ h }) =>
                                  setResizePreview({ id: p.id, h }),
                                onCommit: ({ h }) => {
                                  setResizePreview(null);
                                  void applyLayout([
                                    {
                                      id: p.id,
                                      x: 0,
                                      y: gl.y,
                                      w: 1,
                                      h,
                                      zone,
                                    },
                                  ]);
                                },
                              }
                            : null
                        }
                      />
                    </div>
                  )}
                </SortableTile>
              );
            })}
            </div>
          </SortableContext>
        )}
      </div>
    </DroppableCanvas>
  );
}

// ---------------------------------------------------------------------------
// Grid canvas — multi-column CSS grid with free 2-D placement + resize.
// ---------------------------------------------------------------------------

interface GridCanvasProps extends CanvasSharedProps {
  preset: GridPreset;
  measureRef: (el: HTMLDivElement | null) => void;
  measuredRect: DOMRect | null;
}

function GridCanvas({
  pins,
  preset,
  editMode,
  chrome,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  anyDragging,
  isOver,
  applyLayout,
  measureRef,
  measuredRect,
  channelId,
}: GridCanvasProps) {
  if (!editMode && pins.length === 0) return null;
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });

  // Live resize preview — updates immediately as the user drags the handle.
  // Clears on commit; the store's optimistic update from `applyLayout` takes
  // over from there.
  const [resizePreview, setResizePreview] = useState<{
    id: string;
    w: number;
    h: number;
  } | null>(null);

  // Ensure enough grid rows are reserved so every pin has room and empty
  // canvases still show a usable drop area. The row count is reflected in
  // the canvas's min-height so the guides + tiles share the same vertical
  // extent.
  const rowCount = useMemo(() => {
    let max = 0;
    for (const p of pins) {
      const gl = toGridLayout(p);
      max = Math.max(max, gl.y + gl.h);
    }
    return Math.max(max + 2, 12);
  }, [pins]);

  const contentHeight = rowCount * preset.rowHeight + (rowCount - 1) * GAP_PX;

  // Cell width in px: canvas inner width (less the p-3 = 24px padding +
  // (cols-1) gaps) / cols. Used by ResizeHandles to convert pixel delta to
  // column delta. Falls back to a sensible default until the first measure.
  const cellWidthPx = useMemo(() => {
    const innerW = measuredRect ? Math.max(0, measuredRect.width - 24) : 720;
    return (innerW - (preset.cols.lg - 1) * GAP_PX) / preset.cols.lg;
  }, [measuredRect, preset.cols.lg]);

  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: `repeat(${preset.cols.lg}, minmax(0, 1fr))`,
    gridAutoRows: `${preset.rowHeight}px`,
    gap: `${GAP_PX}px`,
    minHeight: contentHeight,
  };

  return (
    <DroppableCanvas
      zone="grid"
      label="Grid"
      extraClass={GRID_CLASSES}
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      measureRef={measureRef}
    >
      <div className="relative flex-1 flex flex-col overflow-hidden p-3">
        <div style={gridStyle} className="relative flex-1">
          {editMode && (
            <EditModeGridGuides
              cols={preset.cols.lg}
              rowHeight={preset.rowHeight}
              rowGap={GAP_PX}
            />
          )}
          {pins.length === 0 ? (
            editMode ? (
              <div
                className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-center opacity-40 select-none px-4"
                style={{ gridColumn: "1 / -1", gridRow: "1 / -1" }}
              >
                Drop widgets here to keep them on this dashboard page without surfacing them on chat.
              </div>
            ) : null
          ) : (
            pins.map((p) => {
              const gl = toGridLayout(p);
              // Live preview during resize: swap in the transient w/h so the
              // tile expands/contracts in real time. Commit reverts to the
              // persisted grid_layout when the pointer is released.
              const isResizing = resizePreview?.id === p.id;
              const effW = isResizing ? resizePreview!.w : gl.w;
              const effH = isResizing ? resizePreview!.h : gl.h;
              const gridColumn = `${gl.x + 1} / span ${effW}`;
              const gridRow = `${gl.y + 1} / span ${effH}`;
              return (
                <GridTile
                  key={p.id}
                  id={p.id}
                  gridColumn={gridColumn}
                  gridRow={gridRow}
                >
                  {(binding) => (
                    <div
                      ref={binding.setNodeRef}
                      {...binding.attributes}
                      className="relative min-w-0 min-h-0"
                      style={binding.style}
                    >
                      <TileShell
                        binding={{ ...binding, setNodeRef: () => {} }}
                        pin={p}
                        editMode={editMode}
                        chrome={chrome}
                        scope={dashboardScope()}
                        onUnpin={onUnpin}
                        onEnvelopeUpdate={onEnvelopeUpdate}
                        onEditPin={onEditPin}
                        resize={
                          editMode
                            ? {
                                edges: ["s", "e", "se"] as ResizeEdge[],
                                initial: { w: gl.w, h: gl.h },
                                cellPx: {
                                  w: cellWidthPx + GAP_PX,
                                  h: preset.rowHeight + GAP_PX,
                                },
                                clampW: { min: 1, max: preset.cols.lg - gl.x },
                                clampH: { min: 2 },
                                onResizing: ({ w, h }) =>
                                  setResizePreview({ id: p.id, w, h }),
                                onCommit: ({ w, h }) => {
                                  setResizePreview(null);
                                  void applyLayout([
                                    {
                                      id: p.id,
                                      x: gl.x,
                                      y: gl.y,
                                      w,
                                      h,
                                      zone: "grid",
                                    },
                                  ]);
                                },
                              }
                            : null
                        }
                      />
                    </div>
                  )}
                </GridTile>
              );
            })
          )}
        </div>
      </div>
    </DroppableCanvas>
  );
}

// ---------------------------------------------------------------------------
// Tile shell — wraps PinnedToolWidget + (optional) resize handles.
// ---------------------------------------------------------------------------

interface TileShellProps {
  binding: ExternalDragBinding;
  pin: WidgetDashboardPin;
  editMode: boolean;
  chrome: DashboardChrome;
  scope: WidgetScope;
  onUnpin: (id: string) => void;
  onEnvelopeUpdate: (id: string, env: ToolResultEnvelope) => void;
  onEditPin: (id: string) => void;
  railMode?: boolean;
  resize:
    | null
    | {
        edges: ResizeEdge[];
        initial: { w: number; h: number };
        cellPx: { w: number; h: number };
        clampW: { min: number; max: number };
        clampH: { min: number; max?: number };
        onResizing?: (size: { w: number; h: number }) => void;
        onCommit: (size: { w: number; h: number }) => void;
      };
}

function TileShell({
  binding,
  pin,
  editMode,
  chrome,
  scope,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  railMode,
  resize,
}: TileShellProps) {
  return (
    <>
      <PinnedToolWidget
        widget={asPinnedWidget(pin)}
        scope={scope}
        onUnpin={onUnpin}
        onEnvelopeUpdate={onEnvelopeUpdate}
        editMode={editMode}
        onEdit={() => onEditPin(pin.id)}
        borderless={chrome.borderless}
        hoverScrollbars={chrome.hoverScrollbars}
        railMode={railMode}
        externalDrag={binding}
      />
      {resize && (
        <ResizeHandles
          edges={resize.edges}
          initial={resize.initial}
          cellPx={resize.cellPx}
          clampW={resize.clampW}
          clampH={resize.clampH}
          onResizing={resize.onResizing}
          onCommit={resize.onCommit}
        />
      )}
    </>
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
