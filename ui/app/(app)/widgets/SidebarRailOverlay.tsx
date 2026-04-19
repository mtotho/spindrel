/** Visual overlay over the leftmost 2 columns of the dashboard grid.
 *
 *  When a channel dashboard is in edit mode, this overlay marks the
 *  "sidebar rail" — anything a user places at `x === 0 && w <= 2` also
 *  renders in the channel's left OmniPanel. The overlay is purely
 *  decorative: membership is computed from the pin's `grid_layout`, not
 *  from any flag stored here.
 *
 *  Pointer events pass through so the user can drag over/through the
 *  overlay when moving widgets in or out of the rail.
 */
import { Pin } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface Props {
  /** Total row count of the grid, to size the overlay height. */
  rowCount: number;
  /** Row height in px (matches `ROW_HEIGHT` on the dashboard page). */
  rowHeight: number;
  /** Vertical gap between rows in px (matches grid margin). */
  rowGap: number;
  /** How many pins currently live in the rail (grid_layout.x === 0 && w <= 2). */
  railCount: number;
}

export function SidebarRailOverlay({
  rowCount,
  rowHeight,
  rowGap,
  railCount,
}: Props) {
  // 2 cols out of 12 = 1/6 of the grid width.
  const heightPx = Math.max(
    rowCount * rowHeight + (rowCount - 1) * rowGap,
    rowHeight * 6,
  );

  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute left-0 top-0",
        "rounded-lg border border-dashed border-accent/40",
        "bg-accent/[0.04]",
      )}
      style={{
        width: "calc((100% - 11 * 12px) / 12 * 2 + 12px)",
        height: heightPx,
        zIndex: 0,
      }}
    >
      <div
        className={cn(
          "absolute top-2 left-2 right-2",
          "inline-flex items-center gap-1.5 rounded-md",
          "bg-accent/15 px-2 py-0.5",
          "text-[10px] font-semibold uppercase tracking-wider text-accent",
        )}
      >
        <Pin size={10} />
        <span>Sidebar rail</span>
      </div>
      <div
        className="absolute bottom-2 left-2 right-2 text-center text-[10px] text-accent/70"
      >
        {railCount === 0
          ? "Drop widgets here to show them on the channel"
          : `${railCount} pinned to sidebar`}
      </div>
    </div>
  );
}
