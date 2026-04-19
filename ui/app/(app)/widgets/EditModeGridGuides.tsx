/** Subtle visual guides shown only while editing a channel dashboard.
 *
 *  Three layers, all pointer-events-none and rendered as the FIRST sibling
 *  inside the relative grid wrapper. RGL grid items use `transform` which
 *  creates per-tile stacking contexts; siblings with the same z-index paint
 *  in DOM order, so guides drawn first sit beneath the tiles without any
 *  z-index manipulation. (The previous `zIndex: -1` was hiding them behind
 *  the page background.)
 *
 *  1. Faint cell grid — solid 1px lines at every column boundary and every
 *     row boundary. Renders snap targets without competing with widgets.
 *  2. A single rail divider line at `x = railZoneCols` — brighter than the
 *     cell grid; lifts to accent when a widget is being dragged into zone.
 *  3. A small "← Sidebar" label hugging the divider so the rule is
 *     learnable without copy.
 */
import { PanelLeft } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface Props {
  /** Total column count of the grid (lg breakpoint). */
  cols: number;
  /** Row height in px (matches grid `rowHeight`). */
  rowHeight: number;
  /** Pixel gap between cells (matches grid `margin`). */
  rowGap: number;
  /** Leftmost N columns that count as the rail zone. */
  railZoneCols: number;
  /** Number of rows of guide grid to draw. */
  gridRowCount: number;
  /** True while the user is dragging a widget whose left edge is inside the rail zone. */
  dragXInRail: boolean;
}

export function EditModeGridGuides({
  cols,
  rowHeight,
  rowGap,
  railZoneCols,
  gridRowCount,
  dragXInRail,
}: Props) {
  // Width of one cell + the trailing gap (cell pitch). Used both for the
  // vertical-line gradient stop math and to position the rail divider at
  // the right edge of the railZoneCols-th cell.
  const cellPitch = `calc((100% - ${cols - 1} * ${rowGap}px) / ${cols} + ${rowGap}px)`;
  // Divider sits at the seam between rail-zone cell N and zone+1 cell.
  // That's `railZoneCols * cellPitch - rowGap/2` from the left.
  const dividerLeft = `calc(${cellPitch} * ${railZoneCols} - ${rowGap / 2}px)`;
  const heightPx = Math.max(
    gridRowCount * rowHeight + (gridRowCount - 1) * rowGap,
    rowHeight * 8,
  );

  // Direct rgba so we don't depend on a parent `color` token resolving in the
  // gradient — keeps the guides visible regardless of inherited color.
  const cellLineColor = "rgba(148, 163, 184, 0.10)"; // slate-400 @ 10%
  const dividerColor = dragXInRail
    ? "rgba(96, 165, 250, 0.75)" // accent-400 @ 75%
    : "rgba(96, 165, 250, 0.40)"; // accent-400 @ 40%
  const labelColor = dragXInRail
    ? "rgba(96, 165, 250, 1.0)"
    : "rgba(148, 163, 184, 0.85)";

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute left-0 right-0 top-0"
      style={{ height: heightPx }}
    >
      {/* Cell grid: vertical lines at every column boundary, horizontal lines
          at every row. Solid colors with their own alpha — no parent opacity
          needed. */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `
            repeating-linear-gradient(
              to right,
              transparent 0,
              transparent calc(${cellPitch} - 1px),
              ${cellLineColor} calc(${cellPitch} - 1px),
              ${cellLineColor} ${cellPitch}
            ),
            repeating-linear-gradient(
              to bottom,
              transparent 0,
              transparent ${rowHeight + rowGap - 1}px,
              ${cellLineColor} ${rowHeight + rowGap - 1}px,
              ${cellLineColor} ${rowHeight + rowGap}px
            )
          `,
        }}
      />

      {/* Rail divider: 1px vertical line marking the rail-zone boundary. */}
      <div
        className="absolute top-0 bottom-0 transition-colors duration-150"
        style={{
          left: dividerLeft,
          width: 1,
          backgroundColor: dividerColor,
        }}
      />

      {/* Sidebar label: hugs the divider on the rail side. Small but legible.
          Sits ~6px left of the divider; padding gives it visual weight. */}
      <div
        className={cn(
          "absolute inline-flex items-center gap-1 rounded px-1.5 py-0.5",
          "text-[10px] font-medium uppercase tracking-wider transition-colors duration-150",
        )}
        style={{
          top: 4,
          left: `calc(${dividerLeft} - 78px)`,
          color: labelColor,
          backgroundColor: dragXInRail
            ? "rgba(96, 165, 250, 0.10)"
            : "rgba(148, 163, 184, 0.06)",
        }}
      >
        <PanelLeft size={10} />
        <span>Sidebar</span>
      </div>
    </div>
  );
}
