/** Subtle visual guides shown only while editing a channel dashboard.
 *
 *  Three layers, all behind the grid (`zIndex: -1`, pointer-events disabled):
 *
 *  1. Faint cell grid — vertical and horizontal lines at every snap target,
 *     so users can see where the grid lives while dragging.
 *  2. A single rail divider line at `x = railZoneCols` — marks the boundary
 *     between "shows up in the channel sidebar" (left) and "dashboard only"
 *     (right). Drawn slightly more prominently than the cell grid.
 *  3. A small "← Sidebar" label hugging the divider so the rule is
 *     learnable without copy.
 *
 *  All three brighten when the user is actively dragging a widget into the
 *  rail zone (`dragXInRail = true`).
 *
 *  No tinted background, no dashed border, no chip. The rail isn't a
 *  separate region — it's just one part of the same grid with a different
 *  consequence.
 */
import { PanelLeft } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface Props {
  /** Total column count of the grid (lg breakpoint, since this only renders on desktop). */
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
  // Each cell occupies `(100% - (cols-1)*gap) / cols` of width plus `gap`
  // between cells. The rail divider sits at the *right edge* of the
  // railZoneCols-th cell, which is `railZoneCols * cellWidth + railZoneCols * gap - gap/2`
  // from the left (centered in the gap so it lines up with the visual seam).
  const cellWidthExpr = `((100% - ${cols - 1} * ${rowGap}px) / ${cols})`;
  const dividerLeft = `calc(${cellWidthExpr} * ${railZoneCols} + ${railZoneCols - 1} * ${rowGap}px + ${rowGap / 2}px)`;
  const heightPx = Math.max(
    gridRowCount * rowHeight + (gridRowCount - 1) * rowGap,
    rowHeight * 6,
  );

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0"
      style={{ zIndex: -1, height: heightPx }}
    >
      {/* Cell grid: vertical lines at every column boundary, horizontal lines
          at every row. Faint enough to fade against widget content but
          present enough to read snap targets while dragging. */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `
            repeating-linear-gradient(
              to right,
              transparent 0,
              transparent calc(${cellWidthExpr} + ${rowGap}px - 1px),
              currentColor calc(${cellWidthExpr} + ${rowGap}px - 1px),
              currentColor calc(${cellWidthExpr} + ${rowGap}px)
            ),
            repeating-linear-gradient(
              to bottom,
              transparent 0,
              transparent ${rowHeight + rowGap - 1}px,
              currentColor ${rowHeight + rowGap - 1}px,
              currentColor ${rowHeight + rowGap}px
            )
          `,
          color: "rgb(var(--color-text-muted))",
          opacity: 0.04,
        }}
      />

      {/* Rail divider: 1px vertical line marking the rail-zone boundary.
          Slightly brighter than the cell grid; lifts to accent during drag. */}
      <div
        className="absolute top-0 bottom-0 w-px transition-colors duration-150"
        style={{
          left: dividerLeft,
          backgroundColor: dragXInRail
            ? "rgb(var(--color-accent) / 0.7)"
            : "rgb(var(--color-accent) / 0.25)",
        }}
      />

      {/* Sidebar label: hugs the divider on the rail side. Tiny — the line
          carries the meaning, the label just teaches the rule the first time. */}
      <div
        className={cn(
          "absolute top-0 inline-flex items-center gap-1 px-1.5 py-0.5",
          "text-[10px] uppercase tracking-wider transition-colors duration-150",
        )}
        style={{
          // Place the label so its right edge aligns ~6px left of the divider.
          left: `calc(${dividerLeft} - 70px)`,
          color: dragXInRail
            ? "rgb(var(--color-accent))"
            : "rgb(var(--color-text-muted))",
          opacity: dragXInRail ? 1 : 0.7,
        }}
      >
        <PanelLeft size={10} />
        <span>Sidebar</span>
      </div>
    </div>
  );
}
