/** Visual guides shown only while editing a dashboard.
 *
 *  Five layers, all pointer-events-none and rendered as the FIRST sibling
 *  inside the relative grid wrapper. RGL grid items use `transform` which
 *  creates per-tile stacking contexts; siblings with the same z-index paint
 *  in DOM order, so guides drawn first sit beneath the tiles without any
 *  z-index manipulation.
 *
 *  1. Faint cell grid — solid 1px lines at every column boundary and every
 *     row boundary. Renders snap targets without competing with widgets.
 *  2. Column-index tick row (only while dragging) — numbered 1..N across the
 *     top, tied to the breakpoint's column count.
 *  3. Rail divider (channel dashboards only) — marks the leftmost chat-rail
 *     boundary at ``x = railZoneCols``. Pops to accent when a drag targets it.
 *  4. Dock-right divider (channel dashboards only) — mirrors rail on the
 *     right, at ``x = cols - dockRightCols``.
 *  5. Header band (channel dashboards only) — a horizontal band at ``y = 0``,
 *     ``h = 1``, spanning the columns between the two dividers. Pops when
 *     a 1-row-tall tile is dragged there.
 *
 *  Each channel-zone glows only while a drag intersects it — the rest of the
 *  time they sit at a calm cell-grid alpha. Edit-mode still shows all three
 *  statically so the regions are discoverable before the first drag.
 */
import { ArrowRight, PanelLeft, PanelTop } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface Props {
  /** Total column count of the grid (lg breakpoint). */
  cols: number;
  /** Row height in px (matches grid `rowHeight`). */
  rowHeight: number;
  /** Pixel gap between cells (matches grid `margin`). */
  rowGap: number;
  /** Leftmost N columns that count as the chat-rail zone. */
  railZoneCols: number;
  /** Rightmost N columns that count as the chat dock-right zone. */
  dockRightCols: number;
  /** Number of rows of guide grid to draw. */
  gridRowCount: number;
  /** True while the user is dragging a widget whose left edge is inside the rail zone. */
  dragXInRail: boolean;
  /** True while the user is dragging a widget whose left edge is inside the dock-right zone. */
  dragXInDockRight: boolean;
  /** True while the user is dragging a 1-row-tall tile whose top edge sits in the header band. */
  dragInHeader: boolean;
  /** True while any widget is being dragged — triggers column-index ticks. */
  dragging: boolean;
  /** Only channel dashboards render the chat-zone bands (rail / dock / header);
   *  user dashboards show the cell grid and column indices without a chat
   *  layout concept. */
  showChatZones: boolean;
}

export function EditModeGridGuides({
  cols,
  rowHeight,
  rowGap,
  railZoneCols,
  dockRightCols,
  gridRowCount,
  dragXInRail,
  dragXInDockRight,
  dragInHeader,
  dragging,
  showChatZones,
}: Props) {
  // Width of one cell + the trailing gap (cell pitch). Used for vertical
  // divider positioning and column-tick layout.
  const cellPitch = `calc((100% - ${cols - 1} * ${rowGap}px) / ${cols} + ${rowGap}px)`;
  const railLeft = `calc(${cellPitch} * ${railZoneCols} - ${rowGap / 2}px)`;
  const dockLeft = `calc(${cellPitch} * ${cols - dockRightCols} - ${rowGap / 2}px)`;
  // Header band: y=0, h=1. Thin strip one row tall starting at the top.
  const headerBandHeight = rowHeight;
  const heightPx = Math.max(
    gridRowCount * rowHeight + (gridRowCount - 1) * rowGap,
    rowHeight * 8,
  );

  // Direct rgba so we don't depend on a parent `color` token resolving in the
  // gradient — keeps the guides visible regardless of inherited color.
  const cellLineColor = "rgba(148, 163, 184, 0.10)"; // slate-400 @ 10%
  const idleDivider = "rgba(96, 165, 250, 0.40)"; // accent-400 @ 40%
  const activeDivider = "rgba(96, 165, 250, 0.85)"; // accent-400 @ 85%
  const idleLabel = "rgba(148, 163, 184, 0.85)";
  const activeLabel = "rgba(96, 165, 250, 1.0)";
  const idleLabelBg = "rgba(148, 163, 184, 0.06)";
  const activeLabelBg = "rgba(96, 165, 250, 0.15)";

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute left-0 right-0 top-0"
      style={{ height: heightPx }}
    >
      {/* 1. Cell grid: vertical lines at every column boundary, horizontal
             lines at every row. */}
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

      {/* 2. Column-index tick row — only while dragging. */}
      {dragging && (
        <div
          className="absolute left-0 right-0 -top-4 flex text-[10px] font-mono text-text-dim/70 tabular-nums"
          aria-hidden
        >
          {Array.from({ length: cols }).map((_, i) => (
            <span
              key={i}
              className="flex-1 text-center"
              style={{ marginRight: i < cols - 1 ? rowGap : 0 }}
            >
              {i + 1}
            </span>
          ))}
        </div>
      )}

      {showChatZones && (
        <>
          {/* 3. Rail divider (left) + label */}
          <div
            className="absolute top-0 bottom-0 transition-all duration-150"
            style={{
              left: railLeft,
              width: dragXInRail ? 2 : 1,
              backgroundColor: dragXInRail ? activeDivider : idleDivider,
              boxShadow: dragXInRail
                ? "0 0 8px rgba(96, 165, 250, 0.55)"
                : "none",
            }}
          />
          <div
            className={cn(
              "absolute inline-flex items-center gap-1 rounded px-1.5 py-0.5",
              "text-[10px] font-medium uppercase tracking-wider transition-colors duration-150",
            )}
            style={{
              top: 4,
              left: `calc(${railLeft} - 92px)`,
              color: dragXInRail ? activeLabel : idleLabel,
              backgroundColor: dragXInRail ? activeLabelBg : idleLabelBg,
            }}
          >
            <PanelLeft size={10} />
            <span>Chat sidebar</span>
          </div>

          {/* 4. Dock-right divider + label */}
          <div
            className="absolute top-0 bottom-0 transition-all duration-150"
            style={{
              left: dockLeft,
              width: dragXInDockRight ? 2 : 1,
              backgroundColor: dragXInDockRight ? activeDivider : idleDivider,
              boxShadow: dragXInDockRight
                ? "0 0 8px rgba(96, 165, 250, 0.55)"
                : "none",
            }}
          />
          <div
            className={cn(
              "absolute inline-flex items-center gap-1 rounded px-1.5 py-0.5",
              "text-[10px] font-medium uppercase tracking-wider transition-colors duration-150",
            )}
            style={{
              top: 4,
              left: `calc(${dockLeft} + 6px)`,
              color: dragXInDockRight ? activeLabel : idleLabel,
              backgroundColor: dragXInDockRight ? activeLabelBg : idleLabelBg,
            }}
          >
            <span>Chat dock</span>
            <ArrowRight size={10} />
          </div>

          {/* 5. Header band — horizontal strip y=0, h=1, spanning the middle
                 columns between the two dividers. */}
          <div
            className="absolute transition-all duration-150"
            style={{
              top: 0,
              left: railLeft,
              width: `calc(${dockLeft} - ${railLeft})`,
              height: headerBandHeight,
              backgroundColor: dragInHeader
                ? "rgba(96, 165, 250, 0.14)"
                : "rgba(96, 165, 250, 0.05)",
              borderBottom: dragInHeader
                ? `2px solid ${activeDivider}`
                : `1px dashed ${idleDivider}`,
              boxShadow: dragInHeader
                ? "0 0 8px rgba(96, 165, 250, 0.35)"
                : "none",
            }}
          />
          <div
            className={cn(
              "absolute inline-flex items-center gap-1 rounded px-1.5 py-0.5",
              "text-[10px] font-medium uppercase tracking-wider transition-colors duration-150",
            )}
            style={{
              top: headerBandHeight + 2,
              left: `calc(${railLeft} + 6px)`,
              color: dragInHeader ? activeLabel : idleLabel,
              backgroundColor: dragInHeader ? activeLabelBg : idleLabelBg,
            }}
          >
            <PanelTop size={10} />
            <span>Chat header</span>
          </div>
        </>
      )}
    </div>
  );
}
