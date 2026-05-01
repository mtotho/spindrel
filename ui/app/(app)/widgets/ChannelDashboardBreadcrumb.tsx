import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Hash, LayoutDashboard, StickyNote } from "lucide-react";

interface Props {
  channelId: string;
  channelName: string | undefined;
  railCount: number;
  pinCount: number;
  /** When present, the workbench chat dock is bound to a scratch sub-session
   *  instead of the parent channel chat. Artifacts and layout stay channel-
   *  scoped; this banner exists to make that split explicit before typing. */
  scratchSessionId?: string | null;
  scratchHref?: string | null;
  /** Right-aligned slot for page-scoped actions (Edit / Pin artifact / Dev) —
   *  mirrors `DashboardTabs.right` so the channel-workbench top bar reads
   *  as one continuous toolbar instead of two stacked rows with chrome
   *  lines between them. */
  right?: ReactNode;
}

/** Single-row top bar that replaces `DashboardTabs` for channel workbenches.
 *  Carries breadcrumb (back to channel + workbench label), the rail/total
 *  counts, and a `right` slot for page actions. Uses the same subtle shadow
 *  as `DashboardTabs` for separation from the grid below — no border.
 *
 *  Workbench layout configuration (grid preset, rail pin, tile chrome) lives
 *  in the channel settings "Workbench" tab — reachable via the settings gear
 *  on the right of this bar. There is no dedicated layout gear here. */
export function ChannelDashboardBreadcrumb({
  channelId,
  channelName,
  railCount,
  pinCount,
  scratchSessionId,
  scratchHref,
  right,
}: Props) {
  return (
    <div
      className="relative flex items-center gap-1.5 sm:gap-2 bg-surface px-2 sm:px-3 py-1.5 text-[12px] shadow-[0_1px_3px_-1px_rgba(0,0,0,0.22)]"
      role="navigation"
      aria-label="Channel workbench breadcrumb"
    >
      <Link
        to={`/channels/${channelId}`}
        className="inline-flex min-w-0 items-center gap-1 rounded-md px-1.5 py-1 text-text-muted hover:bg-surface-overlay hover:text-text transition-colors sm:px-2"
        title="Back to channel"
        aria-label="Back to channel"
      >
        <ArrowLeft size={13} className="shrink-0" />
        <Hash size={12} className="shrink-0" />
        <span className="font-medium truncate max-w-[9rem] sm:max-w-none">
          {channelName ?? "channel"}
        </span>
      </Link>
      <span className="hidden sm:inline text-text-dim" aria-hidden>
        /
      </span>
      {/* Workbench label: icon-only on mobile, full label on sm+. */}
      <span className="inline-flex shrink-0 items-center gap-1.5 text-text">
        <LayoutDashboard size={13} className="text-accent" />
        <span className="hidden sm:inline font-semibold">Channel workbench</span>
      </span>
      {/* Rail/total chip — compact tabular count, md+ only. Full breakdown
          lives in the tooltip; the bar stays visually tight. */}
      <span
        className="hidden md:inline text-[11px] text-text-dim tabular-nums"
        title={`${railCount} in chat rail · ${pinCount} pinned artifacts`}
      >
        {railCount}/{pinCount}
      </span>
      {scratchSessionId && (
        <div
          className="ml-1 hidden shrink-0 items-center gap-1.5 rounded-full border border-surface-border bg-surface-overlay px-2.5 py-1 text-[11px] text-text-dim xl:flex"
          title="Chat replies on this workbench go to the current session. Artifacts and layout still belong to the parent channel."
        >
          <StickyNote size={12} className="shrink-0 text-text-dim" />
          <span className="font-medium">Session chat</span>
          {scratchHref && (
            <Link
              to={scratchHref}
              className="shrink-0 rounded-full border border-surface-border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-text-dim transition-colors hover:bg-surface-overlay"
            >
              Open
            </Link>
          )}
        </div>
      )}
      {right && (
        <div className="ml-auto flex shrink-0 items-center gap-1.5 pl-2 sm:gap-2 sm:pl-3">
          {right}
        </div>
      )}
    </div>
  );
}
