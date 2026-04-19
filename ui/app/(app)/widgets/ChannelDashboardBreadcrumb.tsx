import { Link } from "react-router-dom";
import { ArrowLeft, Hash, LayoutDashboard } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface Props {
  channelId: string;
  channelName: string | undefined;
  railCount: number;
  pinCount: number;
}

/** Breadcrumb that replaces `DashboardTabs` when the current route is a
 *  channel dashboard. Keeps the user oriented ("I'm on a channel's
 *  dashboard, not the global tab bar") and provides a one-click route back
 *  to the channel chat. */
export function ChannelDashboardBreadcrumb({
  channelId,
  channelName,
  railCount,
  pinCount,
}: Props) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-b border-surface-border bg-surface px-3 py-1.5",
        "text-[12px]",
      )}
      role="navigation"
      aria-label="Channel dashboard breadcrumb"
    >
      <Link
        to={`/channels/${channelId}`}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
        title="Back to channel"
        aria-label="Back to channel"
      >
        <ArrowLeft size={13} />
        <Hash size={12} />
        <span className="font-medium">{channelName ?? "channel"}</span>
      </Link>
      <span className="text-text-dim" aria-hidden>
        /
      </span>
      <span className="inline-flex items-center gap-1.5 text-text">
        <LayoutDashboard size={13} className="text-accent" />
        <span className="font-semibold">Channel dashboard</span>
      </span>
      <span className="ml-auto text-[11px] uppercase tracking-wider text-text-dim">
        {railCount} in rail · {pinCount} total
      </span>
    </div>
  );
}
