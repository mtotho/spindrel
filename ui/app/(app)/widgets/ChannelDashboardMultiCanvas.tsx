/**
 * ChannelDashboardMultiCanvas — four canvases, one DndContext.
 *
 * Each canvas mirrors its chat-runtime chrome so edit mode looks like
 * reality:
 *   - Rail   ↔ OmniPanel          (bare flex-col, ~300px, no card bg)
 *   - Header ↔ ChannelHeaderChip  (centered chip pill strip)
 *   - Grid   ↔ ChatMessageArea    (bare surface, fills height)
 *   - Dock   ↔ WidgetDockRight    (bare flex-col, ~320px, no card bg)
 *
 * Edit-mode affordances are layered on top as a dashed overlay ring that
 * brightens on `isOver`. Widgets themselves still carry their own tile
 * border — the only chrome on any canvas is the widgets.
 *
 * Drag gestures:
 *   - Within rail / dock (vertical): `SortableContext` (y-ordered).
 *   - Within header (horizontal):    `SortableContext` (x-ordered).
 *   - Within grid (2-D):             `useDraggable` + pointer-to-cell snap.
 *   - Cross-canvas:                  drop onto another `DroppableCanvas`.
 *
 * Resize:
 *   - Rail / dock tiles:  south edge handle (h only; w locked to 1).
 *   - Grid tiles:         south / east / south-east handles.
 *   - Header chips:       east edge handle (w only; h locked to 1).
 *
 * Layout source of truth: every pin's `grid_layout.{x,y,w,h}` + `zone`.
 * All persistence goes through `applyLayout([{id, zone, x, y, w, h}])`.
 */
import {
  useCallback,
  useMemo,
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

// Widths mirror the runtime OmniPanel (300px default) + WidgetDockRight (320px).
const RAIL_WIDTH_PX = 300;
const DOCK_WIDTH_PX = 320;
// Header strip rendered as a compact 12-cell grid so chips can span 1-12 cells.
const HEADER_COLS = 12;
// Chip row height matches ChannelHeaderChip's h-8 pill.
const HEADER_ROW_HEIGHT = 32;
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
  const headerMeasure = useCanvasMeasure();

  // Default tile sizes used when a cross-canvas drop needs to assign fresh
  // coords (the source canvas's x/y/w/h doesn't translate).
  const defaultForZone = useCallback(
    (zone: ChatZone): { x: number; y: number; w: number; h: number } => {
      switch (zone) {
        case "rail":
        case "dock":
          return { x: 0, y: 0, w: 1, h: 6 };
        case "header":
          return { x: 0, y: 0, w: 2, h: 1 };
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
      <div className="flex flex-col gap-3 h-full min-h-0">
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
          measure={headerMeasure}
        />

        <div className="flex-1 flex flex-col gap-4 min-h-0 lg:flex-row lg:gap-3">
          <ListCanvas
            zone="rail"
            widthPx={RAIL_WIDTH_PX}
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
            rowHeight={preset.rowHeight}
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
            widthPx={DOCK_WIDTH_PX}
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
            rowHeight={preset.rowHeight}
          />
        </div>
      </div>

      <DragOverlay dropAnimation={null}>
        {activePin && (
          <div className="opacity-80 pointer-events-none">
            <PinnedToolWidget
              widget={asPinnedWidget(activePin)}
              scope={
                activePin.zone === "header"
                  ? { kind: "channel", channelId, compact: "chip" }
                  : { kind: "dashboard", channelId }
              }
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
// Header canvas — horizontal sortable strip of chips (12-cell grid).
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

interface HeaderCanvasProps extends CanvasSharedProps {
  measure: ReturnType<typeof useCanvasMeasure>;
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
  applyLayout,
  channelId,
  measure,
}: HeaderCanvasProps) {
  if (!editMode && pins.length === 0) return null;
  // Chip scope in BOTH modes so the author sees exactly what the chat shows.
  const chipScope: WidgetScope = { kind: "channel", channelId, compact: "chip" };
  const ids = pins.map((p) => p.id);

  // Live width resize preview — swap in the pending `w` so the chip snaps
  // during the drag. Clears on commit; store's optimistic update takes over.
  const [resizePreview, setResizePreview] = useState<{ id: string; w: number } | null>(null);

  // Cell width in px — derived from the strip's measured inner width. Used
  // by the chip's `e`-edge resize handle to convert pointer delta to column
  // delta. Falls back until the first measure lands.
  const cellWidthPx = useMemo(() => {
    const innerW = measure.rect ? Math.max(0, measure.rect.width - 24) : 480;
    return (innerW - (HEADER_COLS - 1) * 4) / HEADER_COLS;
  }, [measure.rect]);

  return (
    <DroppableCanvas
      zone="header"
      extraClass="w-full flex justify-center"
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      ringRadius="9999px"
    >
      <div
        ref={measure.setRef}
        className={
          "relative inline-flex items-center justify-center px-3 py-1.5 rounded-full "
          + (pins.length > 0 ? "bg-surface-raised/50 backdrop-blur-md shadow-sm" : "")
        }
        style={{ minHeight: HEADER_ROW_HEIGHT + 12 }}
      >
        {pins.length === 0 ? (
          editMode ? (
            <EmptyCanvasHint message="Drop widgets here to show as compact chips above the channel chat." />
          ) : null
        ) : (
          <SortableContext items={ids} strategy={horizontalListSortingStrategy}>
            <div
              className="flex items-center gap-1.5"
              style={{ minWidth: HEADER_COLS * cellWidthPx }}
            >
              {pins.map((p) => {
                const gl = toGridLayout(p);
                const effW = resizePreview?.id === p.id ? resizePreview.w : gl.w;
                const tileWidthPx = Math.max(
                  60,
                  effW * cellWidthPx + (effW - 1) * 4,
                );
                return (
                  <SortableTile key={p.id} id={p.id}>
                    {(binding) => (
                      <div
                        ref={binding.setNodeRef}
                        {...binding.attributes}
                        className="relative"
                        style={{
                          ...binding.style,
                          width: tileWidthPx,
                          flex: `0 0 ${tileWidthPx}px`,
                        }}
                      >
                        <TileShell
                          binding={{ ...binding, setNodeRef: () => {} }}
                          pin={p}
                          editMode={editMode}
                          chrome={chrome}
                          scope={chipScope}
                          onUnpin={onUnpin}
                          onEnvelopeUpdate={onEnvelopeUpdate}
                          onEditPin={onEditPin}
                          resize={
                            editMode
                              ? {
                                  edges: ["e"] as ResizeEdge[],
                                  initial: { w: gl.w, h: 1 },
                                  cellPx: {
                                    w: cellWidthPx + 4,
                                    h: HEADER_ROW_HEIGHT,
                                  },
                                  clampW: { min: 1, max: HEADER_COLS },
                                  clampH: { min: 1, max: 1 },
                                  onResizing: ({ w }) =>
                                    setResizePreview({ id: p.id, w }),
                                  onCommit: ({ w }) => {
                                    setResizePreview(null);
                                    void applyLayout([
                                      {
                                        id: p.id,
                                        x: gl.x,
                                        y: 0,
                                        w,
                                        h: 1,
                                        zone: "header",
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
// List canvas — used by rail + dock (vertical 1-column lists with resizable H).
// ---------------------------------------------------------------------------

interface ListCanvasProps extends CanvasSharedProps {
  zone: "rail" | "dock";
  widthPx: number;
  emptyMessage: string;
  rowHeight: number;
}

function ListCanvas({
  zone,
  widthPx,
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
  rowHeight,
}: ListCanvasProps) {
  if (!editMode && pins.length === 0) return null;
  const ids = pins.map((p) => p.id);
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });
  const [resizePreview, setResizePreview] = useState<{ id: string; h: number } | null>(null);

  // Bare column — matches OmniPanel (rail) / WidgetDockRight (dock) runtime
  // chrome after those cards were stripped. Width mirrors the runtime default
  // so tiles land where they will on the chat screen.
  const extraStyle: CSSProperties = {
    width: "100%",
    flexShrink: 0,
  };
  const extraClass = "order-2 lg:order-none flex flex-col h-full";

  return (
    <div
      className="w-full lg:shrink-0"
      style={{ width: widthPx }}
    >
      <DroppableCanvas
        zone={zone}
        extraClass={extraClass}
        extraStyle={extraStyle}
        editMode={editMode}
        anyDragging={anyDragging}
        isOver={isOver}
      >
        <div className="relative flex-1 min-h-[120px] overflow-y-auto px-2 py-2">
          {editMode && <EditModeGridGuides cols={1} rowHeight={rowHeight} rowGap={GAP_PX} />}
          {pins.length === 0 ? (
            editMode ? <EmptyCanvasHint message={emptyMessage} /> : null
          ) : (
            <SortableContext items={ids} strategy={verticalListSortingStrategy}>
              <div className="relative flex flex-col gap-2">
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
                                    cellPx: { w: widthPx, h: rowHeight + GAP_PX },
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grid canvas — multi-column CSS grid with free 2-D placement + resize.
// The inner grid div sits inside a flex-1 wrapper so the dashed drop ring +
// grid guides extend over the full column height, even when pins are sparse.
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
    height: "100%",
    minHeight: 0,
  };

  return (
    <DroppableCanvas
      zone="grid"
      extraClass="flex-1 min-w-0 order-1 lg:order-none flex"
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      measureRef={measureRef}
    >
      <div className="relative flex-1 flex flex-col overflow-hidden p-3 min-h-[240px]">
        {editMode && (
          <EditModeGridGuides
            cols={preset.cols.lg}
            rowHeight={preset.rowHeight}
            rowGap={GAP_PX}
          />
        )}
        <div style={gridStyle} className="relative flex-1">
          {pins.length === 0 ? (
            editMode ? (
              <div
                className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-center opacity-40 select-none px-4"
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
