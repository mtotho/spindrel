/**
 * ChannelDashboardMultiCanvas — four canvases, one DndContext.
 *
 * Each canvas mirrors its chat-runtime chrome so edit mode looks like
 * reality:
 *   - Rail   ↔ OmniPanel          (bare flex-col, runtime panel width)
 *   - Header ↔ ChannelHeaderChip  (floating 2-row top rail)
 *   - Grid   ↔ ChatMessageArea    (bare surface, fills height)
 *   - Dock   ↔ WidgetDockRight    (bare flex-col, runtime panel width)
 *
 * Edit-mode affordances are layered on top as a dashed overlay ring that
 * brightens on `isOver`. Widgets themselves still carry their own tile
 * border — the only chrome on any canvas is the widgets.
 *
 * Drag gestures:
 *   - Within rail / dock (vertical): `SortableContext` (y-ordered).
 *   - Within header (2-D):           `useDraggable` + pointer-to-cell snap.
 *   - Within grid (2-D):             `useDraggable` + pointer-to-cell snap.
 *   - Cross-canvas:                  drop onto another `DroppableCanvas`.
 *
 * Resize:
 *   - Rail / dock tiles:  south edge handle (h only; w locked to 1).
 *   - Grid tiles:         south / east / south-east handles.
 *   - Header tiles:       east / south / south-east handles (2-row max).
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
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useThemeTokens } from "@/src/theme/tokens";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import type { WidgetLayout } from "@/src/components/chat/renderers/InteractiveHtmlRenderer";
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
import { CHANNEL_PANEL_DEFAULT_WIDTH } from "@/src/lib/channelPanelLayout";
import { resolveDashboardCanvasMinHeight } from "@/src/lib/dashboardCanvasHeight";
import { getSuggestedWidgetSize, getWidgetLayoutBounds } from "@/src/lib/widgetLayoutHints";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { EditModeGridGuides } from "./EditModeGridGuides";
import {
  DroppableCanvas,
  GridTile,
  ResizeHandles,
  SortableTile,
  pointerToCell,
  clampPlacement,
  sequentialYLayout,
  useCanvasMeasure,
  type ExternalDragBinding,
  type ResizeEdge,
  type TileBox,
} from "./DashboardDnd";

// Widths mirror the runtime chat workbench/dock defaults.
const RAIL_WIDTH_PX = CHANNEL_PANEL_DEFAULT_WIDTH;
const DOCK_WIDTH_PX = CHANNEL_PANEL_DEFAULT_WIDTH;
const HEADER_ROW_HEIGHT_PX = 32;
const HEADER_MAX_ROWS = 2;
const GAP_PX = 12;
// Matches the inner `p-3` padding on the canvas content wrappers — kept in a
// constant so pointerToCell math and the ghost target overlay agree.
const CANVAS_INNER_PADDING = 12;

interface BodyCanvasMetrics {
  innerWidth: number;
  centerColWidth: number;
  centerTrackWidth: number;
  centerStartX: number;
  dockStartX: number;
}

function computeBodyCanvasMetrics(
  canvasWidth: number,
  centerCols: number,
): BodyCanvasMetrics {
  const innerWidth = Math.max(1, canvasWidth - CANVAS_INNER_PADDING * 2);
  const totalGaps = (centerCols + 1) * GAP_PX;
  const centerColWidth = Math.max(
    1,
    (innerWidth - RAIL_WIDTH_PX - DOCK_WIDTH_PX - totalGaps) / centerCols,
  );
  const centerTrackWidth =
    centerCols * centerColWidth + Math.max(0, centerCols - 1) * GAP_PX;
  const centerStartX = RAIL_WIDTH_PX + GAP_PX;
  const dockStartX = centerStartX + centerTrackWidth + GAP_PX;
  return { innerWidth, centerColWidth, centerTrackWidth, centerStartX, dockStartX };
}

function zoneFromBodyX(
  relX: number,
  metrics: BodyCanvasMetrics,
): "rail" | "grid" | "dock" {
  if (relX < metrics.centerStartX - GAP_PX / 2) return "rail";
  if (relX >= metrics.dockStartX - GAP_PX / 2) return "dock";
  return "grid";
}

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

function boxesOverlap(a: GridLayoutItem, b: GridLayoutItem): boolean {
  return (
    a.x < b.x + b.w
    && a.x + a.w > b.x
    && a.y < b.y + b.h
    && a.y + a.h > b.y
  );
}

function isChipLikeHeaderLayout(layout: GridLayoutItem): boolean {
  return layout.h === 1 && layout.w <= 4;
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
  const [activeDragSize, setActiveDragSize] = useState<{ width: number; height: number } | null>(null);
  const [activeDragOffset, setActiveDragOffset] = useState<{ x: number; y: number } | null>(null);
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
        .sort((a, b) => {
          const ag = toGridLayout(a);
          const bg = toGridLayout(b);
          return ag.y - bg.y || ag.x - bg.x;
        }),
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
  const bodyMeasure = useCanvasMeasure();
  const headerMeasure = useCanvasMeasure();
  const bodyMetrics = useMemo(
    () =>
      bodyMeasure.rect
        ? computeBodyCanvasMetrics(bodyMeasure.rect.width, preset.cols.lg)
        : null,
    [bodyMeasure.rect, preset.cols.lg],
  );

  // Default w/h used when a cross-canvas drop creates fresh coords (the
  // source canvas's dimensions don't translate — a chip can't stay a chip
  // after landing in the main grid). x/y are derived pointer-aware.
  const defaultSizeForZone = useCallback(
    (
      zone: ChatZone,
      presentation?: WidgetDashboardPin["widget_presentation"] | null,
    ): { w: number; h: number } => {
      const fallback = (() => {
        switch (zone) {
          case "rail":
          case "dock":
            return { w: 1, h: 6 };
          case "header":
            return { w: 6, h: 2 };
          case "grid":
          default:
            return { w: preset.defaultTile.w, h: preset.defaultTile.h };
        }
      })();
      return getSuggestedWidgetSize(presentation, zone, fallback, preset.cols.lg);
    },
    [preset.cols.lg, preset.defaultTile],
  );

  const nextGridPlacement = useCallback(
    (excludeIds: string[] = []): GridLayoutItem => {
      const size = { w: preset.defaultTile.w, h: preset.defaultTile.h };
      const occupied = pins
        .filter((p) => p.zone === "grid" && !excludeIds.includes(p.id))
        .map(toGridLayout);
      const maxSlots = Math.max(occupied.length + pins.length + 4, 8);
      for (let slot = 0; slot < maxSlots; slot += 1) {
        const candidate: GridLayoutItem = {
          x: (slot % 2) * size.w,
          y: Math.floor(slot / 2) * size.h,
          w: size.w,
          h: size.h,
        };
        if (!occupied.some((existing) => boxesOverlap(candidate, existing))) {
          return candidate;
        }
      }
      return {
        x: 0,
        y: Math.ceil(occupied.length / 2) * size.h,
        w: size.w,
        h: size.h,
      };
    },
    [pins, preset.defaultTile.h, preset.defaultTile.w],
  );

  /** DOM-measure the insertion index for a vertical list canvas (rail/dock).
   *  Walks every tile's bounding rect and returns how many sit above the
   *  pointer's midline. Works regardless of scroll, padding, or CSS flex
   *  gaps — no extra measure hook needed. */
  const insertionIndexByY = useCallback(
    (zone: "rail" | "dock", pointerY: number): number => {
      const tiles = document.querySelectorAll<HTMLElement>(
        `[data-pin-zone="${zone}"]`,
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
    setActiveDragOffset(null);
    const rect = e.active.rect.current.initial;
    if (rect?.width && rect?.height) {
      setActiveDragSize({ width: rect.width, height: rect.height });
    } else {
      const node = document.querySelector<HTMLElement>(`[data-pin-id="${String(e.active.id)}"]`);
      const fallbackRect = node?.getBoundingClientRect();
      setActiveDragSize(
        fallbackRect?.width && fallbackRect?.height
          ? { width: fallbackRect.width, height: fallbackRect.height }
          : null,
      );
    }
    const pe = e.activatorEvent as PointerEvent | null;
    if (pe && typeof pe.clientX === "number") {
      setDragPointer({ x: pe.clientX, y: pe.clientY });
      if (rect) {
        setActiveDragOffset({
          x: Math.max(0, Math.min(rect.width, pe.clientX - rect.left)),
          y: Math.max(0, Math.min(rect.height, pe.clientY - rect.top)),
        });
      } else {
        const node = document.querySelector<HTMLElement>(`[data-pin-id="${String(e.active.id)}"]`);
        const fallbackRect = node?.getBoundingClientRect();
        setActiveDragOffset(
          fallbackRect
            ? {
                x: Math.max(0, Math.min(fallbackRect.width, pe.clientX - fallbackRect.left)),
                y: Math.max(0, Math.min(fallbackRect.height, pe.clientY - fallbackRect.top)),
              }
            : null,
        );
      }
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
      const size = defaultSizeForZone(targetZone, pin.widget_presentation);

      // Grid: pointer-snap the pin's top-left to a cell; coords are absolute
      // so no sibling rewrite is needed (grid uses CSS Grid positioning).
      if (targetZone === "grid") {
        const rect = bodyMeasure.rect;
        const metrics = bodyMetrics;
        if (!rect || !metrics) return;
        const { x, y } = pointerToCell(
          clientX - (activeDragOffset?.x ?? 0) - rect.left - CANVAS_INNER_PADDING - metrics.centerStartX,
          clientY - (activeDragOffset?.y ?? 0) - rect.top - CANVAS_INNER_PADDING,
          {
            cols: preset.cols.lg,
            rowHeight: preset.rowHeight,
            gap: GAP_PX,
            canvasWidth: metrics.centerTrackWidth,
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

      // Header: pointer-snapped placement on the 2-row top rail.
      if (targetZone === "header") {
        const rect = headerMeasure.rect;
        if (!rect) return;
        const { x, y } = pointerToCell(
          clientX - (activeDragOffset?.x ?? 0) - rect.left,
          clientY - (activeDragOffset?.y ?? 0) - rect.top,
          {
            cols: preset.cols.lg,
            rowHeight: HEADER_ROW_HEIGHT_PX,
            gap: GAP_PX,
            canvasWidth: Math.max(1, rect.width),
          },
        );
        const placement = clampPlacement(x, y, size.w, Math.min(size.h, HEADER_MAX_ROWS), preset.cols.lg);
        try {
          await applyLayout([{
            id: pinId,
            zone: "header",
            ...placement,
            y: Math.min(HEADER_MAX_ROWS - Math.min(size.h, HEADER_MAX_ROWS), placement.y),
            h: Math.min(size.h, HEADER_MAX_ROWS),
          }]);
          pulseMoved(pinId);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to move widget");
        }
        return;
      }

      // Rail / dock: in the unified canvas these are still absolute-y zones,
      // not compact sortable lists. Drop should therefore honor the target
      // row and only push colliding siblings downward, preserving any
      // intentional vertical gaps already present in the column.
      const rect = bodyMeasure.rect;
      if (!rect) return;
      const sourceLayout = toGridLayout(pin);
      const nextHeight = pin.zone === targetZone ? sourceLayout.h : size.h;
      const { y: targetY } = pointerToCell(
        0,
        clientY - (activeDragOffset?.y ?? 0) - rect.top - CANVAS_INNER_PADDING,
        {
          cols: 1,
          rowHeight: preset.rowHeight,
          gap: GAP_PX,
          canvasWidth: targetZone === "rail" ? RAIL_WIDTH_PX : DOCK_WIDTH_PX,
        },
      );
      const entries = [
        ...pins
          .filter((p) => p.zone === targetZone && p.id !== pinId)
          .map((p) => {
            const gl = toGridLayout(p);
            return { id: p.id, y: gl.y, h: gl.h, zone: p.zone, active: false as const };
          }),
        { id: pinId, y: targetY, h: nextHeight, zone: targetZone, active: true as const },
      ].sort((a, b) => (a.y - b.y) || (a.active ? -1 : 1));
      let occupiedUntil = 0;
      const items = entries.map((entry) => {
        const y = Math.max(entry.y, occupiedUntil);
        occupiedUntil = y + entry.h;
        return {
          id: entry.id,
          zone: entry.zone,
          x: 0,
          y,
          w: 1,
          h: entry.h,
        };
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
      bodyMeasure.rect,
      headerMeasure.rect,
      bodyMetrics,
      preset.cols.lg,
      preset.rowHeight,
      activeDragOffset,
    ],
  );

  const commitSortableReorder = useCallback(
    async (zone: "rail" | "dock", fromId: string, toId: string) => {
      // Match the filter/sort used by the render so arrayMove operates on the
      // same array the user sees. Otherwise the reorder index math drifts
      // from the visual order.
      const zonePins = pins
        .filter((p) => p.zone === zone)
        .slice()
        .sort((a, b) => toGridLayout(a).y - toGridLayout(b).y);
      const ids = zonePins.map((p) => p.id);
      const from = ids.indexOf(fromId);
      const to = ids.indexOf(toId);
      if (from < 0 || to < 0 || from === to) return;
      const reordered = arrayMove(ids, from, to);
      const byId = new Map<string, GridLayoutItem>(
        zonePins.map((p) => [p.id, toGridLayout(p)]),
      );
      const nextLayout = sequentialYLayout(reordered, 6, byId);
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
      const rect = bodyMeasure.rect;
      const metrics = bodyMetrics;
      if (!rect || !metrics) return;
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) return;
      const existing = toGridLayout(pin);
      const cfg = {
        cols: preset.cols.lg,
        rowHeight: preset.rowHeight,
        gap: GAP_PX,
        canvasWidth: metrics.centerTrackWidth,
      };
      const { x, y } = pointerToCell(
        clientX - (activeDragOffset?.x ?? 0) - rect.left - CANVAS_INNER_PADDING - metrics.centerStartX,
        clientY - (activeDragOffset?.y ?? 0) - rect.top - CANVAS_INNER_PADDING,
        cfg,
      );
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
    [pins, applyLayout, preset.cols.lg, preset.rowHeight, bodyMeasure, bodyMetrics, pulseMoved, activeDragOffset],
  );

  const commitHeaderMove = useCallback(
    async (pinId: string, clientX: number, clientY: number) => {
      const rect = headerMeasure.rect;
      const pin = pins.find((p) => p.id === pinId);
      if (!rect || !pin) return;
      const existing = toGridLayout(pin);
      const { x, y } = pointerToCell(
        clientX - (activeDragOffset?.x ?? 0) - rect.left,
        clientY - (activeDragOffset?.y ?? 0) - rect.top,
        {
          cols: preset.cols.lg,
          rowHeight: HEADER_ROW_HEIGHT_PX,
          gap: GAP_PX,
          canvasWidth: Math.max(1, rect.width),
        },
      );
      const placement = clampPlacement(x, y, existing.w, Math.min(existing.h, HEADER_MAX_ROWS), preset.cols.lg);
      const next = {
        ...placement,
        y: Math.min(HEADER_MAX_ROWS - Math.min(existing.h, HEADER_MAX_ROWS), placement.y),
        h: Math.min(existing.h, HEADER_MAX_ROWS),
      };
      try {
        await applyLayout([{ id: pinId, zone: "header", ...next }]);
        pulseMoved(pinId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to place widget");
      }
    },
    [pins, applyLayout, preset.cols.lg, headerMeasure.rect, pulseMoved, activeDragOffset],
  );

  const onDragEnd = useCallback(
    async (e: DragEndEvent) => {
      const activeId = String(e.active.id);
      const overId = e.over?.id != null ? String(e.over.id) : null;
      setActiveDragId(null);
      setActiveDragSize(null);
      setActiveDragOffset(null);
      setOverZone(null);
      setDragPointer(null);
      const active = pins.find((p) => p.id === activeId);
      if (!active) return;

      // Release pointer position — dnd-kit doesn't expose it directly, so
      // reconstruct from the activator start + running delta.
      const pe = (e.activatorEvent as PointerEvent | null);
      const releaseX = (pe?.clientX ?? 0) + e.delta.x;
      const releaseY = (pe?.clientY ?? 0) + e.delta.y;

      // Resolve the target zone: header is the only independent droppable;
      // the body surface derives its zone from the pointer's x-position.
      let targetZone: ChatZone | null = null;
      if (overId) {
        if (overId.startsWith("canvas:header")) {
          targetZone = "header";
        } else {
          const overPin = pins.find((p) => p.id === overId);
          if (overPin?.zone === "header") targetZone = "header";
        }
      }
      if (targetZone == null) {
        const rect = bodyMeasure.rect;
        const metrics = bodyMetrics;
        if (!rect || !metrics) return;
        const relX = releaseX - rect.left - CANVAS_INNER_PADDING;
        const relY = releaseY - rect.top - CANVAS_INNER_PADDING;
        if (relX < 0 || relY < 0 || relX > metrics.innerWidth) return;
        targetZone = zoneFromBodyX(relX, metrics);
      }

      if (targetZone !== active.zone) {
        // Cross-canvas move — pointer-aware placement.
        await commitCrossCanvasMove(activeId, targetZone, releaseX, releaseY);
        return;
      }

      // Same-zone move:
      if (targetZone === "header") {
        await commitHeaderMove(activeId, releaseX, releaseY);
        return;
      }

      if (targetZone === "grid") {
        // Free placement: snap pointer to a cell.
        await commitGridMove(activeId, releaseX, releaseY);
        return;
      }

      if (targetZone === "rail" || targetZone === "dock") {
        await commitCrossCanvasMove(activeId, targetZone, releaseX, releaseY);
      }
    },
    [pins, bodyMeasure.rect, bodyMetrics, applyLayout, commitCrossCanvasMove, commitGridMove, commitHeaderMove, pulseMoved],
  );

  const activePin = activeDragId ? pins.find((p) => p.id === activeDragId) ?? null : null;

  const bodyOverZone = useMemo(() => {
    if (!dragPointer || !bodyMeasure.rect || !bodyMetrics) return null;
    const relX = dragPointer.x - bodyMeasure.rect.left - CANVAS_INNER_PADDING;
    const relY = dragPointer.y - bodyMeasure.rect.top - CANVAS_INNER_PADDING;
    if (relX < 0 || relY < 0 || relX > bodyMetrics.innerWidth) return null;
    return zoneFromBodyX(relX, bodyMetrics);
  }, [dragPointer, bodyMeasure.rect, bodyMetrics]);

  /** Ghost target for the 2-row header rail. */
  const headerGhost = useMemo(() => {
    if (overZone !== "header" || !dragPointer || !activePin || !headerMeasure.rect) return null;
    const existing = toGridLayout(activePin);
    const { x, y } = pointerToCell(
      dragPointer.x - (activeDragOffset?.x ?? 0) - headerMeasure.rect.left,
      dragPointer.y - (activeDragOffset?.y ?? 0) - headerMeasure.rect.top,
      {
        cols: preset.cols.lg,
        rowHeight: HEADER_ROW_HEIGHT_PX,
        gap: GAP_PX,
        canvasWidth: Math.max(1, headerMeasure.rect.width),
      },
    );
    const placement = clampPlacement(x, y, existing.w, Math.min(existing.h, HEADER_MAX_ROWS), preset.cols.lg);
    return {
      ...placement,
      y: Math.min(HEADER_MAX_ROWS - Math.min(existing.h, HEADER_MAX_ROWS), placement.y),
      h: Math.min(existing.h, HEADER_MAX_ROWS),
    };
  }, [overZone, dragPointer, activePin, headerMeasure.rect, preset.cols.lg, activeDragOffset]);

  /** Ghost target box for the grid canvas — the snapped cell where the
   *  active drag will land on release. Null unless dragging over the grid.
   *  Rendered as a dashed accent outline inside GridCanvas. */
  const gridGhost = useMemo(() => {
    if (overZone === "header" || bodyOverZone !== "grid" || !dragPointer || !activePin) return null;
    const rect = bodyMeasure.rect;
    const metrics = bodyMetrics;
    if (!rect || !metrics) return null;
    const existing = toGridLayout(activePin);
    const { x, y } = pointerToCell(
      dragPointer.x - (activeDragOffset?.x ?? 0) - rect.left - CANVAS_INNER_PADDING - metrics.centerStartX,
      dragPointer.y - (activeDragOffset?.y ?? 0) - rect.top - CANVAS_INNER_PADDING,
      {
        cols: preset.cols.lg,
        rowHeight: preset.rowHeight,
        gap: GAP_PX,
        canvasWidth: metrics.centerTrackWidth,
      },
    );
    return clampPlacement(x, y, existing.w, existing.h, preset.cols.lg);
  }, [overZone, bodyOverZone, dragPointer, activePin, bodyMeasure.rect, bodyMetrics, preset.cols.lg, preset.rowHeight, activeDragOffset]);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragMove={onDragMove}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      <div className="flex flex-col gap-3">
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger"
          >
            {error}
          </div>
        )}

        <UnifiedBodyCanvas
          pins={[...railPins, ...gridPins, ...dockPins]}
          headerPins={headerPins}
          preset={preset}
          editMode={editMode}
          chrome={chrome}
          onUnpin={onUnpin}
          onEnvelopeUpdate={onEnvelopeUpdate}
          onEditPin={onEditPin}
          anyDragging={activeDragId !== null}
          isOver={bodyOverZone !== null}
          overZone={overZone === "header" ? null : bodyOverZone}
          applyLayout={applyLayout}
          measureRef={bodyMeasure.setRef}
          measuredRect={bodyMeasure.rect}
          headerMeasure={headerMeasure}
          headerIsOver={overZone === "header"}
          headerGhost={headerGhost}
          channelId={channelId}
          justMovedId={justMovedId}
          onTileMoved={pulseMoved}
          ghost={gridGhost}
        />
      </div>

      <DragOverlay dropAnimation={null}>
        {activePin && (
          <DragOverlayPreview pin={activePin} size={activeDragSize} />
        )}
      </DragOverlay>
    </DndContext>
  );
}

function DragOverlayPreview({
  pin,
  size,
}: {
  pin: WidgetDashboardPin;
  size: { width: number; height: number } | null;
}) {
  const t = useThemeTokens();
  const title =
    pin.envelope?.display_label
    || pin.envelope?.panel_title
    || pin.tool_name;
  const isChip = pin.zone === "header" && isChipLikeHeaderLayout(toGridLayout(pin));
  const width = size?.width ?? (isChip ? 180 : 320);
  const height = size?.height ?? (isChip ? 32 : Math.max(96, Math.min(240, toGridLayout(pin).h * 18)));
  return (
    <div
      className={
        "pointer-events-none opacity-85 rounded-lg border shadow-2xl backdrop-blur-sm "
        + (isChip ? "px-3 flex items-center" : "px-4 py-3 overflow-hidden")
      }
      style={{
        width,
        height,
        borderColor: `${t.accent}55`,
        background: `${t.surface}ee`,
        boxShadow: "0 18px 40px rgba(0, 0, 0, 0.35)",
      }}
    >
      {isChip ? (
        <div className="truncate text-[12px] font-medium" style={{ color: t.textMuted }}>
          {title}
        </div>
      ) : (
        <div className="flex h-full flex-col gap-3">
          <div className="truncate text-[12px] font-medium uppercase tracking-[0.14em]" style={{ color: t.textDim }}>
            {title}
          </div>
          <div
            className="min-h-0 flex-1 rounded-md"
            style={{
              background: `linear-gradient(180deg, ${t.surfaceRaised} 0%, ${t.surface} 100%)`,
              border: `1px solid ${t.surfaceBorder}55`,
            }}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header canvas — 2-row floating top rail aligned to the center track.
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
  cols: number;
  ghost: { x: number; y: number; w: number; h: number } | null;
  embedded?: boolean;
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
  cols,
  justMovedId,
  onTileMoved,
  ghost,
  embedded = false,
}: HeaderCanvasProps) {
  const t = useThemeTokens();
  const [resizePreview, setResizePreview] = useState<{
    id: string;
    x: number;
    w: number;
    h: number;
  } | null>(null);
  if (!editMode && pins.length === 0) return null;
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });
  const railHeight = HEADER_ROW_HEIGHT_PX * HEADER_MAX_ROWS + GAP_PX * (HEADER_MAX_ROWS - 1);
  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
    gridTemplateRows: `repeat(${HEADER_MAX_ROWS}, ${HEADER_ROW_HEIGHT_PX}px)`,
    gap: `${GAP_PX}px`,
  };

  return (
    <DroppableCanvas
      zone="header"
      extraClass="w-full"
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      ringRadius="12px"
      measureRef={measure.setRef}
    >
      <div
        className={embedded ? "relative min-h-0" : "relative min-h-0 p-3"}
        style={{ minHeight: railHeight + (embedded ? 0 : CANVAS_INNER_PADDING * 2) }}
      >
        <div style={gridStyle} className="relative">
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
                className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[11px] opacity-60"
                style={{ color: t.textMuted }}
              >
                Drop widgets here to float them over chat without consuming page height.
              </div>
            ) : null
          ) : (
            pins.map((pin) => {
              const gl = toGridLayout(pin);
              const preview = resizePreview?.id === pin.id ? resizePreview : null;
              const effX = preview ? preview.x : gl.x;
              const effW = preview ? preview.w : gl.w;
              const effH = preview ? preview.h : gl.h;
              const chipLike = isChipLikeHeaderLayout(gl);
              const bounds = getWidgetLayoutBounds(pin.widget_presentation, "header", cols);
              const scope: WidgetScope = chipLike
                ? { kind: "channel", channelId, compact: "chip" }
                : dashboardScope();
              return (
                <GridTile
                  key={pin.id}
                  id={pin.id}
                  disabled={!editMode}
                  gridColumn={`${effX + 1} / span ${effW}`}
                  gridRow={`${gl.y + 1} / span ${effH}`}
                >
                  {(binding) => (
                    <div
                      ref={binding.setNodeRef}
                      {...binding.attributes}
                      data-pin-id={pin.id}
                      data-pin-zone="header"
                      className={
                        "relative min-w-0 "
                        + (justMovedId === pin.id ? "pin-flash" : "")
                      }
                      style={binding.style}
                    >
                      <TileShell
                        binding={{ ...binding, setNodeRef: () => {} }}
                        pin={pin}
                        editMode={editMode}
                        chrome={chrome}
                        scope={scope}
                        onUnpin={onUnpin}
                        onEnvelopeUpdate={onEnvelopeUpdate}
                        onEditPin={onEditPin}
                        layout={chipLike ? "chip" : "header"}
                        resize={
                          editMode
                            ? {
                                edges: ["s", "e", "se", "w", "sw"] as ResizeEdge[],
                                initial: { x: gl.x, y: gl.y, w: gl.w, h: gl.h },
                                cellPx: {
                                  w:
                                    ((measure.rect?.width ?? 0) - (cols - 1) * GAP_PX)
                                    / cols
                                    + GAP_PX,
                                  h: HEADER_ROW_HEIGHT_PX + GAP_PX,
                                },
                                clampW: { min: bounds.minW, max: bounds.maxW },
                                clampH: { min: bounds.minH, max: bounds.maxH ?? HEADER_MAX_ROWS },
                                showRest: true,
                                onResizing: ({ x, w, h }) =>
                                  setResizePreview({
                                    id: pin.id,
                                    x,
                                    w,
                                    h: Math.min(h, HEADER_MAX_ROWS),
                                  }),
                                onCommit: ({ x, w, h }) => {
                                  setResizePreview(null);
                                  const next = clampPlacement(x, gl.y, w, Math.min(h, HEADER_MAX_ROWS), cols);
                                  void applyLayout([{
                                    id: pin.id,
                                    zone: "header",
                                    ...next,
                                    y: Math.min(HEADER_MAX_ROWS - Math.min(h, HEADER_MAX_ROWS), gl.y),
                                    h: Math.min(h, HEADER_MAX_ROWS),
                                  }]).then(() => onTileMoved?.(pin.id));
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
// Unified body canvas — one logical surface with rail / center grid / dock
// zones. Center keeps the existing 12/24-column coordinate system; rail and
// dock each occupy one fixed-width outer track that mirrors chat runtime.
// ---------------------------------------------------------------------------

interface UnifiedBodyCanvasProps extends CanvasSharedProps {
  headerPins: WidgetDashboardPin[];
  preset: GridPreset;
  measureRef: (el: HTMLDivElement | null) => void;
  measuredRect: DOMRect | null;
  headerMeasure: ReturnType<typeof useCanvasMeasure>;
  headerIsOver: boolean;
  headerGhost: { x: number; y: number; w: number; h: number } | null;
  overZone: "rail" | "grid" | "dock" | null;
  ghost: { x: number; y: number; w: number; h: number } | null;
}

function UnifiedBodyCanvas({
  pins,
  headerPins,
  preset,
  editMode,
  chrome,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
  anyDragging,
  overZone,
  applyLayout,
  measureRef,
  measuredRect,
  headerMeasure,
  headerIsOver,
  headerGhost,
  channelId,
  justMovedId,
  onTileMoved,
  ghost,
}: UnifiedBodyCanvasProps) {
  const t = useThemeTokens();
  const { height: viewportHeight } = useWindowSize();
  const [resizePreview, setResizePreview] = useState<{
    id: string;
    x: number;
    w: number;
    h: number;
  } | null>(null);
  const metrics = useMemo(
    () =>
      measuredRect
        ? computeBodyCanvasMetrics(measuredRect.width, preset.cols.lg)
        : null,
    [measuredRect, preset.cols.lg],
  );
  const centerCellWidth = metrics?.centerColWidth ?? 64;
  const dashboardScope = (): WidgetScope => ({ kind: "dashboard", channelId });
  const headerLeft = metrics ? CANVAS_INNER_PADDING + metrics.centerStartX : 0;
  const headerWidth = metrics?.centerTrackWidth ?? 0;
  const bodyCanvasMinHeight = useMemo(
    () =>
      resolveDashboardCanvasMinHeight({
        viewportHeight,
        canvasTop: measuredRect?.top ?? null,
      }),
    [viewportHeight, measuredRect?.top],
  );
  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns: `${RAIL_WIDTH_PX}px repeat(${preset.cols.lg}, minmax(0, 1fr)) ${DOCK_WIDTH_PX}px`,
    gridAutoRows: `${preset.rowHeight}px`,
    gap: `${GAP_PX}px`,
  };

  return (
    <div
      ref={measureRef}
      data-dashboard-canvas="body"
      className="relative p-3"
      style={{ minHeight: bodyCanvasMinHeight }}
    >
      {editMode && metrics && (
        <>
          <ZoneOverlay
            left={CANVAS_INNER_PADDING}
            width={RAIL_WIDTH_PX}
            isOver={overZone === "rail"}
            t={t}
          />
          <ZoneOverlay
            left={CANVAS_INNER_PADDING + metrics.centerStartX}
            width={metrics.centerTrackWidth}
            isOver={overZone === "grid"}
            t={t}
          />
          <ZoneOverlay
            left={CANVAS_INNER_PADDING + metrics.dockStartX}
            width={DOCK_WIDTH_PX}
            isOver={overZone === "dock"}
            t={t}
          />
          <EditModeGridGuides
            cols={preset.cols.lg}
            rowHeight={preset.rowHeight}
            rowGap={GAP_PX}
          />
        </>
      )}
      {metrics && (
        <div
          className="absolute z-20"
          style={{
            top: CANVAS_INNER_PADDING,
            left: headerLeft,
            width: headerWidth,
          }}
        >
          <HeaderCanvas
            pins={headerPins}
            editMode={editMode}
            chrome={chrome}
            onUnpin={onUnpin}
            onEnvelopeUpdate={onEnvelopeUpdate}
            onEditPin={onEditPin}
            anyDragging={anyDragging}
            isOver={headerIsOver}
            applyLayout={applyLayout}
            channelId={channelId}
            measure={headerMeasure}
            cols={preset.cols.lg}
            justMovedId={justMovedId}
            onTileMoved={onTileMoved}
            ghost={headerGhost}
            embedded
          />
        </div>
      )}
      <div style={gridStyle} className="relative">
        {ghost && (
          <div
            aria-hidden
            className="pointer-events-none"
            style={{
              gridColumn: `${ghost.x + 2} / span ${ghost.w}`,
              gridRow: `${ghost.y + 1} / span ${ghost.h}`,
              border: `1.5px dashed ${t.accent}`,
              borderRadius: 8,
              background: `${t.accent}14`,
              transition: "grid-column 90ms ease-out, grid-row 90ms ease-out",
              zIndex: 2,
            }}
          />
        )}

        {editMode && !pins.some((p) => p.zone === "rail") && (
          <EmptyZoneSlot column="1 / span 1" message="Drop here for the chat sidebar." />
        )}
        {editMode && !pins.some((p) => p.zone === "grid") && (
          <EmptyZoneSlot
            column={`2 / span ${preset.cols.lg}`}
            message="Drop widgets here to keep them on the dashboard."
          />
        )}
        {editMode && !pins.some((p) => p.zone === "dock") && (
          <EmptyZoneSlot column={`${preset.cols.lg + 2} / span 1`} message="Drop here for the right dock." />
        )}

        {pins.map((p) => {
          const gl = toGridLayout(p);
          const preview = resizePreview?.id === p.id ? resizePreview : null;
          const effX = preview ? preview.x : gl.x;
          const effW = preview ? preview.w : gl.w;
          const effH = preview ? preview.h : gl.h;
          const railLike = p.zone === "rail" || p.zone === "dock";
          const bounds = getWidgetLayoutBounds(
            p.widget_presentation,
            railLike ? p.zone : "grid",
            preset.cols.lg,
          );
          const gridColumn =
            p.zone === "rail"
              ? "1 / span 1"
              : p.zone === "dock"
                ? `${preset.cols.lg + 2} / span 1`
                : `${effX + 2} / span ${effW}`;
          const gridRow = `${gl.y + 1} / span ${effH}`;

          return (
            <GridTile
              key={p.id}
              id={p.id}
              disabled={!editMode}
              gridColumn={gridColumn}
              gridRow={gridRow}
            >
              {(binding) => (
                <div
                  ref={binding.setNodeRef}
                  {...binding.attributes}
                  data-pin-id={p.id}
                  data-pin-zone={p.zone}
                  className={
                    "relative min-w-0 "
                    + (railLike ? "" : "min-h-0 ")
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
                    railMode={railLike}
                    resize={
                      editMode
                        ? (railLike
                          ? {
                              edges: ["s"] as ResizeEdge[],
                              initial: { x: 0, y: gl.y, w: 1, h: gl.h },
                              cellPx: { w: RAIL_WIDTH_PX, h: preset.rowHeight + GAP_PX },
                              clampW: { min: 1, max: 1 },
                              clampH: { min: bounds.minH, max: bounds.maxH },
                              showRest: true,
                              onResizing: ({ h }) =>
                                setResizePreview({ id: p.id, x: 0, w: 1, h }),
                              onCommit: ({ h }) => {
                                setResizePreview(null);
                                void applyLayout([
                                  { id: p.id, x: 0, y: gl.y, w: 1, h, zone: p.zone },
                                ]).then(() => onTileMoved?.(p.id));
                              },
                            }
                          : {
                              edges: ["s", "e", "se", "w", "sw"] as ResizeEdge[],
                              initial: { x: gl.x, y: gl.y, w: gl.w, h: gl.h },
                              cellPx: {
                                w: centerCellWidth + GAP_PX,
                                h: preset.rowHeight + GAP_PX,
                              },
                              clampW: { min: bounds.minW, max: bounds.maxW },
                              clampH: { min: bounds.minH, max: bounds.maxH },
                              showRest: true,
                              onResizing: ({ x, w, h }) =>
                                setResizePreview({ id: p.id, x, w, h }),
                              onCommit: ({ x, w, h }) => {
                                setResizePreview(null);
                                void applyLayout([
                                  { id: p.id, x, y: gl.y, w, h, zone: "grid" },
                                ]).then(() => onTileMoved?.(p.id));
                              },
                            })
                        : null
                    }
                  />
                </div>
              )}
            </GridTile>
          );
        })}
      </div>
    </div>
  );
}

function ZoneOverlay({
  left,
  width,
  isOver,
  t,
}: {
  left: number;
  width: number;
  isOver: boolean;
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute top-3 bottom-3 rounded-lg"
      style={{
        left,
        width,
        border: `1px dashed ${isOver ? t.accent : `${t.textDim}22`}`,
        background: isOver ? `${t.accent}0f` : "transparent",
        transition: "border-color 120ms, background-color 120ms",
      }}
    />
  );
}

function EmptyZoneSlot({
  column,
  message,
}: {
  column: string;
  message: string;
}) {
  const t = useThemeTokens();
  return (
    <div
      className="pointer-events-none flex items-start justify-center px-3 py-2 text-[11px] text-center opacity-60 select-none"
      style={{ gridColumn: column, gridRow: "1 / span 2", color: t.textDim }}
    >
      {message}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List canvas — legacy split-canvas implementation retained below for now.
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
  const extraClass = "order-2 lg:order-none flex flex-col self-start";

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
        <div className="relative min-h-[120px] px-2 py-2">
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
                  const bounds = getWidgetLayoutBounds(p.widget_presentation, zone, 1);
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
                                    clampH: { min: bounds.minH, max: bounds.maxH },
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

  // Grid canvas stays rendered even when empty in view mode: it's the
  // middle column of a three-column row (rail / grid / dock), and collapsing
  // it would let rail + dock pack together flush against each other. Reserve
  // the flex space; suppress the drop hint outside edit mode so the empty
  // canvas reads as intentional whitespace, not a missing affordance.
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
      extraClass="order-1 flex min-w-0 self-start lg:order-none lg:flex-1"
      editMode={editMode}
      anyDragging={anyDragging}
      isOver={isOver}
      measureRef={measureRef}
    >
      <div className="relative min-h-[240px] p-3">
        {editMode && (
          <EditModeGridGuides
            cols={preset.cols.lg}
            rowHeight={preset.rowHeight}
            rowGap={GAP_PX}
          />
        )}
        <div style={gridStyle} className="relative">
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
              const bounds = getWidgetLayoutBounds(
                p.widget_presentation,
                "grid",
                preset.cols.lg,
              );
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
                                clampW: { min: bounds.minW, max: bounds.maxW },
                                clampH: { min: bounds.minH, max: bounds.maxH },
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
  layout?: WidgetLayout;
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
  layout,
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
        panelSurface={railMode}
        railMode={railMode}
        layout={layout}
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
