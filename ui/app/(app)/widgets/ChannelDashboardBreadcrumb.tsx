import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Hash, LayoutDashboard, Settings } from "lucide-react";

interface Props {
  channelId: string;
  channelName: string | undefined;
  railCount: number;
  pinCount: number;
  /** Opens the dashboard settings drawer (preset / grid config / etc).
   *  Mirrors the gear icon on `DashboardTabs` so channel dashboards aren't
   *  second-class citizens missing dashboard-scoped controls. */
  onOpenManage?: () => void;
  /** Right-aligned slot for page-scoped actions (Edit / Add widget / Dev) —
   *  mirrors `DashboardTabs.right` so the channel-dashboard top bar reads
   *  as one continuous toolbar instead of two stacked rows with chrome
   *  lines between them. */
  right?: ReactNode;
}

/** Single-row top bar that replaces `DashboardTabs` for channel dashboards.
 *  Carries breadcrumb (back to channel + dashboard label), a gear for
 *  dashboard settings, the rail/total counts, and a `right` slot for
 *  page actions. Uses the same subtle shadow as `DashboardTabs` for
 *  separation from the grid below — no border. */
export function ChannelDashboardBreadcrumb({
  channelId,
  channelName,
  railCount,
  pinCount,
  onOpenManage,
  right,
}: Props) {
  return (
    <div
      className="relative flex items-center gap-1.5 sm:gap-2 bg-surface px-2 sm:px-3 py-1.5 text-[12px] shadow-[0_1px_3px_-1px_rgba(0,0,0,0.22)]"
      role="navigation"
      aria-label="Channel dashboard breadcrumb"
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
      {/* Dashboard label: icon-only on mobile, full label on sm+. */}
      <span className="inline-flex shrink-0 items-center gap-1.5 text-text">
        <LayoutDashboard size={13} className="text-accent" />
        <span className="hidden sm:inline font-semibold">Channel dashboard</span>
      </span>
      {onOpenManage && (
        <button
          type="button"
          onClick={onOpenManage}
          title="Dashboard settings"
          aria-label="Dashboard settings"
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          <Settings size={13} />
        </button>
      )}
      {/* Rail/total chip — compact tabular count, md+ only. Full breakdown
          lives in the tooltip; the bar stays visually tight. */}
      <span
        className="hidden md:inline text-[11px] text-text-dim tabular-nums"
        title={`${railCount} in rail · ${pinCount} total`}
      >
        {railCount}/{pinCount}
      </span>
      {right && (
        <div className="ml-auto flex shrink-0 items-center gap-1.5 pl-2 sm:gap-2 sm:pl-3">
          {right}
        </div>
      )}
    </div>
  );
}
