/** Visual guides shown only while editing a user dashboard.
 *
 *  Two layers, pointer-events-none, rendered as the FIRST sibling inside the
 *  relative grid wrapper:
 *
 *  1. Faint cell grid — solid 1px lines at every column boundary and every
 *     row boundary. Renders snap targets without competing with widgets.
 *  2. Column-index tick row (only while dragging) — numbered 1..N across the
 *     top, tied to the breakpoint's column count.
 *
 *  Used by both the user-dashboard single grid and the channel dashboard's
 *  per-canvas grids (see ``ChannelDashboardMultiCanvas``). For a rail/dock
 *  canvas pass ``cols={1}`` — the horizontal row lines are what matter for
 *  snapping there. Chat-zone bands are no longer rendered here; zones are
 *  visually separated by the multi-canvas layout itself.
 */

interface Props {
  /** Total column count of the grid (lg breakpoint). */
  cols: number;
  /** Row height in px (matches grid `rowHeight`). */
  rowHeight: number;
  /** Pixel gap between cells (matches grid `margin`). */
  rowGap: number;
  /** Number of rows of guide grid to draw. */
  gridRowCount: number;
  /** True while any widget is being dragged — triggers column-index ticks. */
  dragging: boolean;
}

export function EditModeGridGuides({
  cols,
  rowHeight,
  rowGap,
  gridRowCount,
  dragging,
}: Props) {
  const cellPitch = `calc((100% - ${cols - 1} * ${rowGap}px) / ${cols} + ${rowGap}px)`;
  const heightPx = Math.max(
    gridRowCount * rowHeight + (gridRowCount - 1) * rowGap,
    rowHeight * 8,
  );
  const cellLineColor = "rgba(148, 163, 184, 0.10)"; // slate-400 @ 10%

  // 1-col canvases (rail / dock) only need horizontal row lines — a vertical
  // gradient at the single column boundary looks like a rogue edge. Skip it.
  const verticalGradient =
    cols > 1
      ? `repeating-linear-gradient(
          to right,
          transparent 0,
          transparent calc(${cellPitch} - 1px),
          ${cellLineColor} calc(${cellPitch} - 1px),
          ${cellLineColor} ${cellPitch}
        ),`
      : "";

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute left-0 right-0 top-0"
      style={{ height: heightPx }}
    >
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: `
            ${verticalGradient}
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
    </div>
  );
}
