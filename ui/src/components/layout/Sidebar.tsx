import { Link, useLocation } from "react-router-dom";
import { Plus, Home } from "lucide-react";
import { useState } from "react";
import { useIntegrationIcons } from "../../api/hooks/useIntegrations";
import { useUIStore, SIDEBAR_DEFAULT_WIDTH } from "../../stores/ui";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useChatStore } from "../../stores/chat";
import { useShallow } from "zustand/react/shallow";
import { cn } from "../../lib/cn";
import { useChannelReadStore } from "../../stores/channelRead";

import { ChannelList } from "./sidebar/ChannelList";
import { SidebarRail } from "./sidebar/SidebarRail";
import { SidebarFooter } from "./sidebar/SidebarFooter";
import { UnreadInboxPanel } from "./sidebar/UnreadInboxPanel";
import { useSidebarShortcut } from "./sidebar/useSidebarShortcut";
import type { Channel } from "../../types/api";

function OrchestratorRow({ channel }: { channel: Channel }) {
  const { pathname } = useLocation();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const isUnread = useChannelReadStore((s) => s.isUnread);
  const isActive = pathname.includes(channel.id);
  const unread = !isActive && isUnread(channel.id, channel.updated_at);

  return (
    <Link to={`/channels/${channel.id}`} onClick={closeMobile}>
      <div
        className={cn(
          "relative flex flex-row items-center gap-2 px-3 py-1.5 mx-1 rounded-md cursor-pointer transition-colors",
          "hover:bg-surface-overlay/60",
          isActive &&
            "bg-accent/[0.10] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[2px] before:h-4 before:rounded-full before:bg-accent",
        )}
      >
        <Home
          size={13}
          className={cn("shrink-0", isActive ? "text-accent" : "text-text-dim")}
        />
        <span
          className={cn(
            "flex-1 truncate text-[13px]",
            isActive
              ? "text-text font-medium"
              : unread
                ? "text-text font-semibold"
                : "text-text-muted font-normal",
          )}
        >
          Orchestrator
        </span>
        {unread && !isActive && (
          <span className="w-2 h-2 rounded-full bg-accent shrink-0 inline-block" />
        )}
      </div>
    </Link>
  );
}

function SidebarPanel() {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const { data: bots } = useBots();
  const { data: iconsData } = useIntegrationIcons();
  const integrationIcons = iconsData?.icons || {};
  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);
  const streamingChannelIds = useChatStore(
    useShallow((s) =>
      Object.entries(s.channels)
        .filter(([, ch]) => Object.keys(ch.turns).length > 0)
        .map(([id]) => id),
    ),
  );
  const streamingSet = new Set(streamingChannelIds);

  const orchestratorChannel = channels?.find((ch) => ch.client_id === "orchestrator:home");

  return (
    <div className="w-full shrink-0 h-full flex flex-col bg-surface border-r border-surface-border/60">
      <div className="scroll-subtle flex-1 overflow-y-auto overflow-x-hidden pb-2">
        {/* System row — orchestrator */}
        {!channelsLoading && orchestratorChannel && (
          <div className="pt-3 pb-1">
            <OrchestratorRow channel={orchestratorChannel} />
          </div>
        )}

        {/* Channels header */}
        <div className="flex flex-row items-center justify-between px-4 pt-3 pb-1 group">
          <span className="text-[11px] font-semibold tracking-[0.14em] uppercase text-text-dim/80">
            Channels
          </span>
          <Link
            to="/channels/new"
            onClick={closeMobile}
            title="New channel"
            aria-label="New channel"
          >
            <div className="w-6 h-6 rounded flex flex-row items-center justify-center cursor-pointer opacity-0 group-hover:opacity-100 hover:bg-surface-overlay/60 transition-all">
              <Plus size={13} className="text-text-dim" />
            </div>
          </Link>
        </div>

        <ChannelList
          channels={channels}
          channelsLoading={channelsLoading}
          botMap={botMap}
          integrationIcons={integrationIcons}
          streamingSet={streamingSet}
        />
      </div>

      <SidebarFooter />
    </div>
  );
}

function startResize(e: React.MouseEvent) {
  e.preventDefault();
  const startX = e.clientX;
  const startWidth = useUIStore.getState().sidebarWidth;
  const onMove = (ev: MouseEvent) => {
    const delta = ev.clientX - startX;
    useUIStore.getState().setSidebarWidth(startWidth + delta);
  };
  const onUp = () => {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const width = useUIStore((s) => s.sidebarWidth);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const [unreadInboxOpen, setUnreadInboxOpen] = useState(false);
  useSidebarShortcut();

  const panelWidth = collapsed ? 0 : width;

  const toggleUnreadInbox = () => {
    if (collapsed && !unreadInboxOpen) {
      toggleSidebar();
    }
    setUnreadInboxOpen((open) => !open);
  };

  return (
    <div className="flex flex-row h-full shrink-0">
      <SidebarRail
        unreadInboxOpen={unreadInboxOpen}
        onToggleUnreadInbox={toggleUnreadInbox}
      />
      <div
        className={cn(
          "relative h-full overflow-hidden transition-[width] duration-200 ease-out motion-reduce:transition-none",
        )}
        style={{ width: panelWidth }}
        aria-hidden={collapsed}
      >
        {unreadInboxOpen ? (
          <UnreadInboxPanel onClose={() => setUnreadInboxOpen(false)} />
        ) : (
          <SidebarPanel />
        )}
        {!collapsed && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            onMouseDown={startResize}
            onDoubleClick={() =>
              useUIStore.getState().setSidebarWidth(SIDEBAR_DEFAULT_WIDTH)
            }
            className="absolute top-0 right-0 bottom-0 w-1 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 transition-colors z-10"
            title="Drag to resize · Double-click to reset"
          />
        )}
      </div>
    </div>
  );
}
