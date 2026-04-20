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
  useEffect,
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
  type DragMoveEvent,
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
  type TileBox,
} from "./DashboardDnd";

// Widths mirror the runtime OmniPanel (300px default) + WidgetDockRight (320px).
const RAIL_WIDTH_PX = 300;
const DOCK_WIDTH_PX = 320;
// Header strip rendered as a compact 12-cell grid so chips can span 1-12 cells.
const HEADER_COLS = 12;
// Chip row height matches ChannelHeaderChip's h-8 pill.
const HEADER_ROW_HEIGHT = 32;
const GAP_PX = 12;
// Matches the inner `p-3` padding on the canvas content wrappers — kept in a
// constant so pointerToCell math and the ghost target overlay agree.
const CANVAS_INNER_PADDING = 12;

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
  /** Live pointer position during a drag. Updated by `onDragMove` and used
   *  by the ghost target overlay in each canvas to show where the active
   *  tile will land on release. Cleared on drag end. */
  const [dragPointer, setDragPointer] = useState<{ x: number; y: number } | null>(null);
  /** Pin id that was just committed (moved or resized). Drives a brief
   *  `pin-flash` pulse so the user sees confirmation at the landing spot.
   *  Cleared ~1200 ms after set. */
  const [justMovedId, setJustMovedId] = useState<string | null>(null);
  const justMovedTimerRef = useRef<number | null>(null);
  const pulseMoved = useCallback((pinId: string) => {
    if (justMovedTimerRef.current) window.clearTimeout(justMovedTimerRef.current);
    setJustMovedId(pinId);
    justMovedTimerRef.current = window.setTimeout(() => {
      setJustMovedId((cur) => (cur === pinId ? null : cur));
    }, 1200);
  }, []);
  useEffect(() => () => {
    if (justMovedTimerRef.current) window.clearTimeout(justMovedTimerRef.current);
  }, []);

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

  // Default w/h used when a cross-canvas drop creates fresh coords (the
  // source canvas's dimensions don't translate — a chip can't stay a chip
  // after landing in the main grid). x/y are derived pointer-aware.
  const defaultSizeForZone = useCallback(
    (zone: ChatZone): { w: number; h: number } => {
      switch (zone) {
        case "rail":
        case "dock":
          return { w: 1, h: 6 };
        case "header":
          return { w: 2, h: 1 };
        case "grid":
        default:
          return { w: preset.defaultTile.w, h: preset.defaultTile.h };
      }
    },
    [preset.defaultTile],
  );

  /** DOM-measure the insertion index for a vertical list canvas (rail/dock).
   *  Walks every tile's bounding rect and returns how many sit above the
   *  pointer's midline. Works regardless of scroll, padding, or CSS flex
   *  gaps — no extra measure hook needed. */
  const insertionIndexByY = useCallback(
    (zone: "rail" | "dock", pointerY: number): number => {
      const tiles = document.querySelectorAll<HTMLElement>(
        `[data-dashboard-canvas="${zone}"] [data-pin-id]`,
      );
      let idx = 0;
      for (const tile of Array.from(tiles)) {
        const r = tile.getBoundingClientRect();
        if (pointerY > r.top + r.height / 2) idx += 1;
        else break;
      }
      return idx;
    },
    [],
  );


  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const onDragStart = useCallback((e: DragStartEvent) => {
    setActiveDragId(String(e.active.id));
    setError(null);
    const pe = e.activatorEvent as PointerEvent | null;
    if (pe && typeof pe.clientX === "number") {
      setDragPointer({ x: pe.clientX, y: pe.clientY });
    }
  }, []);

  const onDragMove = useCallback((e: DragMoveEvent) => {
    // `activatorEvent.clientX/Y` is the start; add the running delta to get
    // the live pointer position. dnd-kit doesn't expose a direct client-xy
    // stream during the drag, so this is the canonical reconstruction.
    const pe = e.activatorEvent as PointerEvent | null;
    if (!pe || typeof pe.clientX !== "number") return;
    setDragPointer({
      x: pe.clientX + e.delta.x,
      y: pe.clientY + e.delta.y,
    });
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
    async (
      pinId: string,
      targetZone: ChatZone,
      clientX: number,
      clientY: number,
    ) => {
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) return;
      if (pin.zone === targetZone) return;
      const size = defaultSizeForZone(targetZone);

      // Grid: pointer-snap the pin's top-left to a cell; coords are absolute
      // so no sibling rewrite is needed (grid uses CSS Grid positioning).
      if (targetZone === "grid") {
        const rect = gridMeasure.rect;
        if (!rect) return;
        const { x, y } = pointerToCell(
          clientX - rect.left,
          clientY - rect.top,
          {
            cols: preset.cols.lg,
            rowHeight: preset.rowHeight,
            gap: GAP_PX,
            canvasWidth: rect.width,
            paddingLeft: CANVAS_INNER_PADDING,
            paddingTop: CANVAS_INNER_PADDING,
          },
        );
        const placement = clampPlacement(x, y, size.w, size.h, preset.cols.lg);
        try {
          await applyLayout([{ id: pinId, zone: "grid", ...placement }]);
          pulseMoved(pinId);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to move widget");
        }
        return;
      }

      // Header: free-placement by pointer X. Each chip is absolutely
      // positioned on a 12-cell grid, so the dropped pin should LAND where
      // the user released — not get swept back to x=0 by a tight repack.
      // Siblings stay put; a rare collision is resolvable by a follow-up
      // drag and far less surprising than "dropped at col 5, landed at 0".
      if (targetZone === "header") {
        const hrect = headerMeasure.rect;
        let x = 0;
        if (hrect) {
          const { x: snapX } = pointerToCell(
            clientX - hrect.left,
            0,
            {
              cols: HEADER_COLS,
              rowHeight: HEADER_ROW_HEIGHT,
              // Chip gap is 4px (see header grid render below).
              gap: 4,
              canvasWidth: hrect.width,
              // Header pill has px-3 horizontal padding.
              paddingLeft: 12,
              paddingTop: 0,
            },
          );
          x = Math.max(0, Math.min(HEADER_COLS - size.w, snapX));
        }
        try {
          await applyLayout([
            { id: pinId, zone: "header", x, y: 0, w: size.w, h: 1 },
          ]);
          pulseMoved(pinId);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to move widget");
        }
        return;
      }

      // Rail / dock: determine insertion index by DOM-measured midpoints,
      // then repack the whole list via `sequentialYLayout` so siblings
      // shift to accommodate the new tile. Vertical stacks compact
      // naturally; pointer Y picks the slot.
      const existing = pins
        .filter((p) => p.zone === targetZone)
        .slice()
        .sort((a, b) => toGridLayout(a).y - toGridLayout(b).y);
      const idx = insertionIndexByY(targetZone as "rail" | "dock", clientY);
      const existingIds = existing.map((p) => p.id);
      const reordered = [
        ...existingIds.slice(0, idx),
        pinId,
        ...existingIds.slice(idx),
      ];
      const byId = new Map<string, GridLayoutItem>(
        existing.map((p) => [p.id, toGridLayout(p)]),
      );
      byId.set(pinId, { x: 0, y: 0, w: size.w, h: size.h });
      const nextLayout = sequentialYLayout(reordered, size.h, byId);
      const items = reordered.map((id) => {
        const coords = nextLayout.get(id)!;
        return id === pinId ? { id, zone: targetZone, ...coords } : { id, ...coords };
      });
      try {
        await applyLayout(items);
        pulseMoved(pinId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to move widget");
      }
    },
    [
      pins,
      applyLayout,
      defaultSizeForZone,
      pulseMoved,
      gridMeasure.rect,
      headerMeasure.rect,
      preset.cols.lg,
      preset.rowHeight,
      insertionIndexByY,
    ],
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
        pulseMoved(fromId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to reorder");
      }
    },
    [pins, applyLayout, pulseMoved],
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
        paddingLeft: CANVAS_INNER_PADDING,
        paddingTop: CANVAS_INNER_PADDING,
      };
      const { x, y } = pointerToCell(clientX - rect.left, clientY - rect.top, cfg);
      const placement = clampPlacement(x, y, existing.w, existing.h, cfg.cols);
      // No-op if the tile didn't actually move cells — still trigger the
      // confirmation pulse so the user knows their drop registered.
      if (
        pin.zone === "grid"
        && placement.x === existing.x
        && placement.y === existing.y
        && placement.w === existing.w
        && placement.h === existing.h
      ) {
        pulseMoved(pinId);
        return;
      }
      try {
        await applyLayout([{ id: pinId, zone: "grid", ...placement }]);
        pulseMoved(pinId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to place widget");
      }
    },
    [pins, applyLayout, preset.cols.lg, preset.rowHeight, gridMeasure, pulseMoved],
  );

  const onDragEnd = useCallback(
    async (e: DragEndEvent) => {
      const activeId = String(e.active.id);
      const overId = e.over?.id != null ? String(e.over.id) : null;
      setActiveDragId(null);
      setOverZone(null);
      setDragPointer(null);
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

      // Release pointer position — dnd-kit doesn't expose it directly, so
      // reconstruct from the activator start + running delta.
      const pe = (e.activatorEvent as PointerEvent | null);
      const releaseX = (pe?.clientX ?? 0) + e.delta.x;
      const releaseY = (pe?.clientY ?? 0) + e.delta.y;

      if (targetZone !== active.zone) {
        // Cross-canvas move — pointer-aware placement.
        await commitCrossCanvasMove(activeId, targetZone, releaseX, releaseY);
        return;
      }

      // Same-zone move:
      if (targetZone === "grid") {
        // Free placement: snap pointer to a cell.
        await commitGridMove(activeId, releaseX, releaseY);
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

  /** Ghost target box for the header canvas — x-only, 1 row tall. Lets
   *  the user see the destination cell span before release, paralleling the
   *  grid canvas ghost. Null unless dragging over the header. */
  const headerGhost = useMemo(() => {
    if (overZone !== "header" || !dragPointer || !activePin) return null;
    const rect = headerMeasure.rect;
    if (!rect) return null;
    const size =
      activePin.zone === "header"
        ? { w: toGridLayout(activePin).w }
        : { w: defaultSizeForZone("header").w };
    const { x } = pointerToCell(
      dragPointer.x - rect.left,
      0,
      {
        cols: HEADER_COLS,
        rowHeight: HEADER_ROW_HEIGHT,
        gap: 4,
        canvasWidth: rect.width,
        paddingLeft: 12,
        paddingTop: 0,
      },
    );
    return { x: Math.max(0, Math.min(HEADER_COLS - size.w, x)), w: size.w };
  }, [overZone, dragPointer, activePin, headerMeasure.rect, defaultSizeForZone]);

  /** Ghost target box for the grid canvas — the snapped cell where the
   *  active drag will land on release. Null unless dragging over the grid.
   *  Rendered as a dashed accent outline inside GridCanvas. */
  const gridGhost = useMemo(() => {
    if (overZone !== "grid" || !dragPointer || !activePin) return null;
    const rect = gridMeasure.rect;
    if (!rect) return null;
    const existing = toGridLayout(activePin);
    const { x, y } = pointerToCell(
      dragPointer.x - rect.left,
      dragPointer.y - rect.top,
      {
        cols: preset.cols.lg,
        rowHeight: preset.rowHeight,
        gap: GAP_PX,
        canvasWidth: rect.width,
        paddingLeft: CANVAS_INNER_PADDING,
        paddingTop: CANVAS_INNER_PADDING,
      },
    );
    return clampPlacement(x, y, existing.w, existing.h, preset.cols.lg);
  }, [overZone, dragPointer, activePin, gridMeasure.rect, preset.cols.lg, preset.rowHeight]);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragMove={onDragMove}
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
          justMovedId={justMovedId}
          onTileMoved={pulseMoved}
          ghost={headerGhost}
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
            justMovedId={justMovedId}
            onTileMoved={pulseMoved}
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
            justMovedId={justMovedId}
            onTileMoved={pulseMoved}
            ghost={gridGhost}
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
            justMovedId={justMovedId}
            onTileMoved={pulseMoved}
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
              hideTitles={chrome.hideTitles}
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
  /** Pin id whose wrapper should briefly apply the `pin-flash` accent pulse
   *  — set by the parent after every successful layout commit so the user
   *  sees where the tile landed. */
  justMovedId?: string | null;
  /** Parent-supplied hook to start a post-commit pulse from inside a canvas
   *  (e.g. after a resize finishes — the parent owns the timer). */
  onTileMoved?: (pinId: string) => void;
}

interface HeaderCanvasProps extends CanvasSharedProps {
  measure: ReturnType<typeof useCanvasMeasure>;
  ghost: { x: number; w: number } | null;
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
  justMovedId,
  onTileMoved,
  ghost,
}: HeaderCanvasProps) {
  const t = useThemeTokens();
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

  // All hooks must run before any early return so React's hook order stays
  // stable when edit mode or pin count toggles the empty-state branch.
  if (!editMode && pins.length === 0) return null;
  // Chip scope in BOTH modes so the author sees exactly what the chat shows.
  const chipScope: WidgetScope = { kind: "channel", channelId, compact: "chip" };
  const ids = pins.map((p) => p.id);

  return (
    <DroppableCanvas
      zone="header"
      extraClass="w-full flex justify-center"
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      ringRadius="9999px"
      measureRef={measure.setRef}
    >
      <div
        className={
          "relative flex items-center justify-center px-3 py-1.5 rounded-full "
          + (pins.length > 0
              ? "bg-surface-raised/50 backdrop-blur-md shadow-sm"
              : editMode
                ? "bg-surface-raised/30"
                : "")
        }
        style={{
          minHeight: HEADER_ROW_HEIGHT + 12,
          // Once a pin lands the pill needs an actual width reference — the
          // inner CSS grid divides into 12 fractional cells, and x coords
          // only mean something if the grid spans the full canvas. Empty
          // edit mode keeps a min-width so the drop target is visible.
          width: pins.length > 0 ? "100%" : undefined,
          minWidth: pins.length === 0 && editMode ? 480 : undefined,
          maxWidth: "100%",
        }}
      >
        {pins.length === 0 ? (
          editMode ? (
            <div className="relative w-full flex items-center justify-center">
              {ghost && (
                <div
                  aria-hidden
                  style={{
                    position: "absolute",
                    left: `calc(${(ghost.x / HEADER_COLS) * 100}% + 12px)`,
                    width: `calc(${(ghost.w / HEADER_COLS) * 100}% - 4px)`,
                    top: 0,
                    bottom: 0,
                    border: `1.5px dashed ${t.accent}`,
                    borderRadius: 9999,
                    background: `${t.accent}14`,
                    transition: "left 90ms ease-out, width 90ms ease-out",
                    pointerEvents: "none",
                  }}
                />
              )}
              <EmptyCanvasHint message="Drop widgets here — they'll show as compact chips above the chat" />
            </div>
          ) : null
        ) : (
          <SortableContext items={ids} strategy={horizontalListSortingStrategy}>
            <div
              style={{
                // CSS grid so each chip's `gl.x` maps to a real horizontal
                // position within the 12-cell header row, mirroring the main
                // grid canvas. Flex-row honored gap only, not x, which made
                // a chip dropped at col 5 render flush-left — fixed here.
                display: "grid",
                gridTemplateColumns: `repeat(${HEADER_COLS}, minmax(0, 1fr))`,
                gridAutoRows: `${HEADER_ROW_HEIGHT}px`,
                columnGap: 4,
                width: "100%",
              }}
            >
              {ghost && (
                <div
                  aria-hidden
                  style={{
                    gridColumn: `${ghost.x + 1} / span ${ghost.w}`,
                    gridRow: 1,
                    border: `1.5px dashed ${t.accent}`,
                    borderRadius: 9999,
                    background: `${t.accent}14`,
                    transition: "grid-column 90ms ease-out",
                    pointerEvents: "none",
                  }}
                />
              )}
              {pins.map((p) => {
                const gl = toGridLayout(p);
                // Clamp defensively. Stale grid_layout from earlier presets
                // could carry w>12 or x≥12; letting that through would break
                // CSS grid placement (line numbers out of range). Server
                // normalises on next write; this keeps render sane today.
                const rawW = resizePreview?.id === p.id ? resizePreview.w : gl.w;
                const effX = Math.max(0, Math.min(HEADER_COLS - 1, gl.x));
                const effW = Math.max(
                  1,
                  Math.min(HEADER_COLS - effX, rawW),
                );
                return (
                  <SortableTile key={p.id} id={p.id}>
                    {(binding) => (
                      <div
                        ref={binding.setNodeRef}
                        {...binding.attributes}
                        data-pin-id={p.id}
                        className={
                          "relative "
                          + (justMovedId === p.id ? "pin-flash" : "")
                        }
                        style={{
                          ...binding.style,
                          gridColumn: `${effX + 1} / span ${effW}`,
                          gridRow: 1,
                          minWidth: 0,
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
                                  edges: ["e", "w"] as ResizeEdge[],
                                  initial: { x: gl.x, y: 0, w: gl.w, h: 1 },
                                  cellPx: {
                                    w: cellWidthPx + 4,
                                    h: HEADER_ROW_HEIGHT,
                                  },
                                  clampW: { min: 1, max: HEADER_COLS },
                                  clampH: { min: 1, max: 1 },
                                  showRest: true,
                                  onResizing: ({ w }) =>
                                    setResizePreview({ id: p.id, w }),
                                  onCommit: ({ x, w }) => {
                                    setResizePreview(null);
                                    void applyLayout([
                                      {
                                        id: p.id,
                                        x,
                                        y: 0,
                                        w,
                                        h: 1,
                                        zone: "header",
                                      },
                                    ]).then(() => onTileMoved?.(p.id));
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
  justMovedId,
  onTileMoved,
}: ListCanvasProps) {
  const [resizePreview, setResizePreview] = useState<{ id: string; h: number } | null>(null);
  // All hooks must run before any early return so React's hook order stays
  // stable when edit mode or pin count toggles the empty-state branch.
  if (!editMode && pins.length === 0) return null;
  const ids = pins.map((p) => p.id);
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });

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
                          data-pin-id={p.id}
                          className={
                            "relative "
                            + (justMovedId === p.id ? "pin-flash" : "")
                          }
                          style={{
                            ...binding.style,
                            height: tileHeightPx,
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
                                    initial: { x: 0, y: gl.y, w: 1, h: gl.h },
                                    cellPx: { w: widthPx, h: rowHeight + GAP_PX },
                                    clampW: { min: 1, max: 1 },
                                    clampH: { min: 2 },
                                    showRest: true,
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
                                      ]).then(() => onTileMoved?.(p.id));
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
  /** Snapped target cell for the in-flight drag — dashed outline overlays
   *  the grid at this position so the user sees where the tile will land. */
  ghost: { x: number; y: number; w: number; h: number } | null;
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
  justMovedId,
  onTileMoved,
  ghost,
}: GridCanvasProps) {
  const t = useThemeTokens();
  // Live resize preview — updates immediately as the user drags the handle.
  // Clears on commit; the store's optimistic update from `applyLayout` takes
  // over from there. `x` tracks west-edge resizes so the tile visibly slides
  // left as the pointer pulls, rather than snapping only on commit.
  const [resizePreview, setResizePreview] = useState<{
    id: string;
    x: number;
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

  // All hooks must run before any early return so React's hook order stays
  // stable when edit mode or pin count toggles the empty-state branch.
  if (!editMode && pins.length === 0) return null;
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });

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
          {ghost && (
            <div
              aria-hidden
              className="pointer-events-none"
              style={{
                gridColumn: `${ghost.x + 1} / span ${ghost.w}`,
                gridRow: `${ghost.y + 1} / span ${ghost.h}`,
                border: `1.5px dashed ${t.accent}`,
                borderRadius: 8,
                background: `${t.accent}14`,
                transition: "grid-column 90ms ease-out, grid-row 90ms ease-out",
                zIndex: 2,
              }}
            />
          )}
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
              const effX = isResizing ? resizePreview!.x : gl.x;
              const effW = isResizing ? resizePreview!.w : gl.w;
              const effH = isResizing ? resizePreview!.h : gl.h;
              const gridColumn = `${effX + 1} / span ${effW}`;
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
                      data-pin-id={p.id}
                      className={
                        "relative min-w-0 min-h-0 "
                        + (justMovedId === p.id ? "pin-flash" : "")
                      }
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
                                edges: ["s", "e", "se", "w", "sw"] as ResizeEdge[],
                                initial: { x: gl.x, y: gl.y, w: gl.w, h: gl.h },
                                cellPx: {
                                  w: cellWidthPx + GAP_PX,
                                  h: preset.rowHeight + GAP_PX,
                                },
                                // clampW.max is the canvas column count — the
                                // handle's west-edge math keeps `x + w` pinned
                                // to the tile's right boundary, so growing
                                // leftward can occupy all cols 0..rightEdge-1
                                // without overflowing.
                                clampW: { min: 1, max: preset.cols.lg },
                                clampH: { min: 2 },
                                showRest: true,
                                onResizing: ({ x, w, h }) =>
                                  setResizePreview({ id: p.id, x, w, h }),
                                onCommit: ({ x, w, h }) => {
                                  setResizePreview(null);
                                  void applyLayout([
                                    {
                                      id: p.id,
                                      x,
                                      y: gl.y,
                                      w,
                                      h,
                                      zone: "grid",
                                    },
                                  ]).then(() => onTileMoved?.(p.id));
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
        initial: TileBox;
        cellPx: { w: number; h: number };
        clampW: { min: number; max: number };
        clampH: { min: number; max?: number };
        showRest?: boolean;
        onResizing?: (box: TileBox) => void;
        onCommit: (box: TileBox) => void;
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
        hideTitles={chrome.hideTitles}
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
      className="flex items-center justify-center py-2.5 px-3 text-[11px] text-center opacity-70 select-none"
      style={{ color: t.textDim }}
    >
      {message}
    </div>
  );
}
