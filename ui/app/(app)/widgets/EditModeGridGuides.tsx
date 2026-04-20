/** Visual guides shown only while editing a dashboard.
 *
 *  One layer, `pointer-events-none`, sized to `absolute inset-0` of the
 *  enclosing positioned container. The parent (the grid/flex content area
 *  INSIDE each canvas) owns the coordinate space — that's what keeps the
 *  cell lines aligned with the actual tile positions. Do NOT render this
 *  OUTSIDE the grid container with its own padding; the gradient offsets
 *  will drift away from the real cells.
 *
 *  For 1-col canvases (rail / dock) only horizontal row lines draw — a lone
 *  vertical line at the single column boundary looks like a rogue edge.
 */

interface Props {
  /** Total column count of the grid at the current breakpoint. */
  cols: number;
  /** Row height in px (must match parent's `grid-auto-rows` / row sizing). */
  rowHeight: number;
  /** Pixel gap between cells (must match parent's `gap`). */
  rowGap: number;
}

export function EditModeGridGuides({ cols, rowHeight, rowGap }: Props) {
  const cellPitch = `calc((100% - ${cols - 1} * ${rowGap}px) / ${cols} + ${rowGap}px)`;
  // slate-400 @ 6% — calmer than before, still visible on dark surfaces.
  const cellLineColor = "rgba(148, 163, 184, 0.06)";

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
      className="pointer-events-none absolute inset-0"
      style={{
        gridColumn: "1 / -1",
        gridRow: "1 / -1",
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
  );
}
