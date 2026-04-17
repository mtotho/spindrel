import { Link, useLocation } from "react-router-dom";
import {
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Home,
  Clock,
  Heart,
  ClipboardList,
  Search,
  Plus,
} from "lucide-react";
import { useIntegrationIcons } from "../../api/hooks/useIntegrations";
import { useUIStore } from "../../stores/ui";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useChannelReadStore } from "../../stores/channelRead";
import { useChatStore } from "../../stores/chat";
import { useShallow } from "zustand/react/shallow";
import { useUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import { SpindrelLogo } from "./SpindrelLogo";
import { useVersion } from "../../api/hooks/useVersion";
import { cn } from "../../lib/cn";

// Sub-components
import { ChannelList } from "./sidebar/ChannelList";
import { SidebarFooterCollapsed, SidebarFooterExpanded } from "./sidebar/SidebarFooter";

/** Format a future ISO timestamp as relative — "in 5m", "in 2h", "in 1d" */
function relativeTime(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now();
  if (diff < 0) return "now";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "< 1m";
  if (mins < 60) return `in ${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `in ${hrs}h`;
  const days = Math.round(hrs / 24);
  return `in ${days}d`;
}

const BOT_DOT_COLORS = [
  "#3b82f6", "#a855f7", "#ec4899", "#ef4444", "#f97316", "#eab308",
  "#22c55e", "#14b8a6", "#06b6d4", "#6366f1", "#f43f5e", "#84cc16",
];

function botDotColor(botId: string): string {
  let hash = 0;
  for (let i = 0; i < botId.length; i++) {
    hash = ((hash << 5) - hash + botId.charCodeAt(i)) | 0;
  }
  return BOT_DOT_COLORS[Math.abs(hash) % BOT_DOT_COLORS.length];
}

export function Sidebar({ mobile = false }: { mobile?: boolean }) {
  const { pathname, search } = useLocation();
  const isTasksListActive = pathname.startsWith("/admin/tasks") && new URLSearchParams(search).get("view") === "list";
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const openPalette = useUIStore((s) => s.openPalette);
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const { data: bots } = useBots();
  const { data: upcomingItems, isLoading: upcomingLoading } = useUpcomingActivity(3);
  const { data: version } = useVersion();
  const { data: iconsData } = useIntegrationIcons();
  const integrationIcons = iconsData?.icons || {};
  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);
  const isUnread = useChannelReadStore((s) => s.isUnread);
  const streamingChannelIds = useChatStore(
    useShallow((s) =>
      Object.entries(s.channels)
        .filter(([, ch]) => Object.keys(ch.turns).length > 0)
        .map(([id]) => id),
    ),
  );
  const streamingSet = new Set(streamingChannelIds);

  const orchestratorChannel = channels?.find((ch) => ch.client_id === "orchestrator:home");
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);

  // -----------------------------------------------------------------------
  // Collapsed: icon rail (56px)
  // -----------------------------------------------------------------------
  if (collapsed) {
    return (
      <div className="w-14 shrink-0 h-full flex flex-col items-center bg-surface">
        <div className="flex-1 overflow-y-auto overflow-x-hidden flex flex-col items-center pt-2.5 pb-2.5 gap-1">
          {/* Logo */}
          <div className="w-10 h-10 mb-1 flex flex-row items-center justify-center text-text">
            <SpindrelLogo size={22} />
          </div>

          {/* Expand toggle */}
          <button
            onClick={toggleSidebar}
            className="sidebar-rail-btn bg-transparent border-none p-0"
            aria-label="Expand sidebar"
          >
            <ChevronRight size={16} className="text-text-dim" />
          </button>

          {/* Search (opens palette) */}
          <button
            onClick={openPalette}
            className="sidebar-rail-btn bg-transparent border-none p-0"
            title={`Search (${isMac ? "\u2318" : "Ctrl"}+K)`}
            aria-label="Open command palette"
          >
            <Search size={18} className="text-text-dim" />
          </button>

          {/* Home (orchestrator) icon */}
          {orchestratorChannel && (() => {
            const orchActive = pathname.includes(orchestratorChannel.id);
            return (
              <Link to={`/channels/${orchestratorChannel.id}`} onClick={closeMobile}>
                <div
                  className={cn("sidebar-rail-btn", orchActive && "bg-accent/15")}
                  title="Home"
                >
                  <Home size={18} className={orchActive ? "text-accent" : "text-text-dim"} />
                </div>
              </Link>
            );
          })()}

          {/* Channels icon */}
          <Link to="/" onClick={closeMobile}>
            <div
              className={cn("sidebar-rail-btn", pathname === "/" && "bg-accent/15")}
              title="Channels"
            >
              <div className="relative">
                <MessageSquare size={18} className={pathname === "/" ? "text-accent" : "text-text-dim"} />
                {channels?.filter((ch) => ch.client_id !== "orchestrator:home").some((ch) => !pathname.includes(ch.id) && isUnread(ch.id, ch.updated_at)) && (
                  <span className="absolute -top-0.5 -right-0.5 w-[7px] h-[7px] rounded-full bg-accent inline-block" />
                )}
              </div>
            </div>
          </Link>

          {/* Upcoming icon */}
          <Link to="/admin/tasks?view=list" onClick={closeMobile}>
            <div
              className={cn("sidebar-rail-btn", isTasksListActive && "bg-accent/15")}
              title="Upcoming Activity"
            >
              <Clock size={18} className={isTasksListActive ? "text-accent" : "text-text-dim"} />
            </div>
          </Link>
        </div>

        <SidebarFooterCollapsed version={version} />
      </div>
    );
  }

  // -----------------------------------------------------------------------
  // Expanded sidebar (260px desktop, flex on mobile)
  // -----------------------------------------------------------------------
  return (
    <div className={cn(
      "shrink-0 h-full flex flex-col bg-surface",
      mobile ? "w-full" : "w-[260px]",
    )}>
      <div className="flex-1 overflow-y-auto overflow-x-hidden pb-2">
        {/* Header */}
        <div className="flex flex-row items-center justify-between px-4 pt-5 pb-3 group">
          <Link to="/">
            <div className="flex flex-row items-center gap-2 cursor-pointer text-text">
              <SpindrelLogo size={22} />
              <span className="text-[13px] font-semibold tracking-[0.15em] text-text/80">SPINDREL</span>
            </div>
          </Link>
          <button
            onClick={toggleSidebar}
            className="sidebar-icon-btn w-8 h-8 rounded flex flex-row items-center justify-center bg-transparent border-none cursor-pointer p-0 opacity-0 group-hover:opacity-100 transition-opacity duration-200"
          >
            <ChevronLeft size={16} className="text-text-dim" />
          </button>
        </div>

        {/* Channel list (orchestrator + regular channels with category grouping) */}
        <ChannelList
          channels={channels}
          channelsLoading={channelsLoading}
          botMap={botMap}
          integrationIcons={integrationIcons}
          mobile={mobile}
          streamingSet={streamingSet}
        />

        {/* Upcoming activity */}
        <div className="px-3 pt-4 pb-1">
          <Link to="/admin/tasks?view=list" onClick={closeMobile}>
            <div className="sidebar-nav-item flex flex-row items-center justify-between px-3 mb-1 rounded cursor-pointer">
              <span className="sidebar-section-label">
                UPCOMING
              </span>
              <Clock size={12} className="text-text-dim" />
            </div>
          </Link>

          {upcomingLoading ? (
            <div className="flex flex-col gap-1">
              {[1, 2].map((i) => (
                <div key={i} className="flex flex-row items-center gap-2.5 px-3 py-1.5">
                  <div className="w-3.5 h-3.5 rounded bg-skeleton/[0.04] animate-pulse" />
                  <div className="flex-1">
                    <div
                      className="h-3 rounded bg-skeleton/[0.04] animate-pulse"
                      style={{ width: `${50 + i * 15}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : !upcomingItems?.length ? (
            <span className="text-xs text-text-dim px-3 py-1 block">
              No upcoming activity
            </span>
          ) : (
            upcomingItems.map((item, idx) => {
              const href = item.type === "heartbeat" && item.channel_id
                ? `/channels/${item.channel_id}/settings#heartbeat`
                : "/admin/tasks";
              return (
                <Link key={`${item.type}-${idx}`} to={href} onClick={closeMobile}>
                  <div className="sidebar-nav-item flex flex-row items-center gap-2 rounded-md px-3 py-1.5 cursor-pointer">
                    {item.type === "heartbeat" ? (
                      <Heart
                        size={13}
                        className={item.in_quiet_hours ? "text-text-dim opacity-40" : "text-warning"}
                      />
                    ) : (
                      <ClipboardList size={13} className="text-accent" />
                    )}
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0 inline-block"
                      style={{ backgroundColor: botDotColor(item.bot_id) }}
                    />
                    <span className="flex-1 text-xs text-text-muted overflow-hidden text-ellipsis whitespace-nowrap">
                      {item.type === "heartbeat" && item.channel_name ? `#${item.channel_name}` : item.title}
                    </span>
                    <span className="text-[10px] text-text-dim shrink-0">
                      {item.scheduled_at ? relativeTime(item.scheduled_at) : ""}
                    </span>
                  </div>
                </Link>
              );
            })
          )}

          <Link to="/admin/tasks?new=1" onClick={closeMobile}>
            <div className="sidebar-nav-item flex flex-row items-center gap-2 rounded-md px-3 py-1.5 mt-1 cursor-pointer text-text-dim hover:text-accent">
              <Plus size={13} />
              <span className="flex-1 text-xs">New task</span>
            </div>
          </Link>
        </div>

      </div>

      <SidebarFooterExpanded pathname={pathname} mobile={mobile} version={version} />
    </div>
  );
}
