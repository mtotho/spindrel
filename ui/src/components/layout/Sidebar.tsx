import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  Container,
  Home,
  Settings,
  Plug,
  Clock,
  Heart,
  ClipboardCheck,
  ClipboardList,
  LayoutDashboard,
  Columns,
  BookOpen,
  Brain,
  HelpCircle,
  Zap,
  Filter,
  Bot,
  Layers,
  FileText,
  Paperclip,
  Key,
  Shield,
  ShieldCheck,
  Activity,
  Server,
  Wrench,
  BarChart3,
  Users,
  HardDrive,
  Code2,
  Hash,
  Lock,
  Sun,
  Moon,
  Mail,
  Camera,
  MessageCircle,
  Terminal,
} from "lucide-react";
import { useMCModules } from "../../api/hooks/useMissionControl";
import { useSidebarSections, useIntegrationIcons, type SidebarSection } from "../../api/hooks/useIntegrations";
import { useUIStore } from "../../stores/ui";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useWorkspaces } from "../../api/hooks/useWorkspaces";
import { useChannelReadStore } from "../../stores/channelRead";
import { useChatStore } from "../../stores/chat";
import { useShallow } from "zustand/react/shallow";
import { useUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import { SpindrelLogo } from "./SpindrelLogo";
import { useVersion } from "../../api/hooks/useVersion";
import { cn } from "../../lib/cn";

// Sub-components
import { ChannelList } from "./sidebar/ChannelList";
import { ALL_NAV_ITEMS, AdminSections, NavLink, RailIcon } from "./sidebar/AdminNav";
import { SidebarFooterCollapsed, SidebarFooterExpanded } from "./sidebar/SidebarFooter";

/** Resolve a lucide icon name string to a component. Falls back to Plug. */
const ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  LayoutDashboard, Columns, BookOpen, Brain, HelpCircle, Settings, Zap, Plug, Filter,
  Bot, Layers, FileText, Paperclip, ClipboardCheck, ClipboardList, Key, Shield, ShieldCheck,
  Activity, Server, Wrench, BarChart3, Users, HardDrive, Code2, Hash, Home,
  MessageSquare, Container, Clock, Heart, Lock, Sun, Moon,
  Mail, Camera, MessageCircle, Terminal,
};
function resolveIcon(name: string): React.ComponentType<{ size?: number; className?: string }> {
  return ICON_MAP[name] || Plug;
}

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

const INTEGRATION_NAV_STORAGE_KEY = "integration-nav-collapsed";

function loadIntegrationCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(INTEGRATION_NAV_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveIntegrationCollapsed(state: Record<string, boolean>) {
  try {
    localStorage.setItem(INTEGRATION_NAV_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

/** Generic integration sidebar section — renders items declared in SETUP manifests */
function IntegrationSidebarSection({
  section,
  pathname,
  mobile,
}: {
  section: SidebarSection;
  pathname: string;
  mobile?: boolean;
}) {
  const hiddenSections = useUIStore((s) => s.hiddenSidebarSections);
  const { data: modulesData } = useMCModules();
  const [collapsed, setCollapsed] = useState(() => {
    const saved = loadIntegrationCollapsed();
    return saved[section.id] ?? false;
  });

  if (hiddenSections.includes(section.id)) return null;

  const items = section.items.map((item) => ({
    label: item.label,
    href: item.href,
    icon: resolveIcon(item.icon),
  }));

  const modules = (modulesData?.modules || []).filter(
    (m) => m.integration_id === section.integration_id,
  );

  const sectionHome = items[0]?.href || "/";
  const segments = sectionHome.replace(/^\//, "").split("/");
  const sectionPrefix =
    segments[0] === "integration" && segments[1]
      ? `/${segments[0]}/${segments[1]}`
      : `/${segments[0] || ""}`;

  const hasActive = items.some((item) => pathname === item.href || pathname.startsWith(item.href)) ||
    modules.some((mod) => pathname === `/integration/${section.integration_id}/module/${mod.module_id}`);

  const SectionIcon = resolveIcon(section.icon);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    const saved = loadIntegrationCollapsed();
    saved[section.id] = next;
    saveIntegrationCollapsed(saved);
  };

  return (
    <div className="px-3 pt-4 pb-1">
      <button
        onClick={toggle}
        className="sidebar-nav-item flex flex-row items-center gap-1.5 px-3 py-1.5 rounded bg-transparent border-none cursor-pointer w-full text-left"
      >
        <SectionIcon size={12} className={hasActive ? "text-accent" : "text-text-dim"} />
        <span className={cn(
          "flex-1 font-semibold tracking-wide",
          mobile ? "text-xs" : "text-[11px]",
          hasActive ? "text-accent" : "text-text-dim",
        )}>
          {section.title}
        </span>
        <ChevronRight
          size={10}
          className={cn(
            "text-text-dim transition-transform duration-150",
            !collapsed && "rotate-90",
          )}
        />
      </button>
      {!collapsed && (
        <>
          {items.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={pathname === item.href || (item.href !== sectionHome && pathname.startsWith(item.href))}
              mobile={mobile}
            />
          ))}
          {modules.map((mod) => {
            const moduleHref = `/integration/${section.integration_id}/module/${mod.module_id}`;
            return (
              <NavLink
                key={mod.module_id}
                item={{
                  label: mod.label,
                  href: moduleHref,
                  icon: resolveIcon(mod.icon),
                }}
                active={pathname === moduleHref}
                mobile={mobile}
              />
            );
          })}
        </>
      )}
    </div>
  );
}

/** Integration rail icons for collapsed sidebar */
function IntegrationRailIcons({
  sections,
  pathname,
  closeMobile,
}: {
  sections: SidebarSection[];
  pathname: string;
  closeMobile: () => void;
}) {
  const hiddenSections = useUIStore((s) => s.hiddenSidebarSections);
  return (
    <>
      {sections
        .filter((s) => !hiddenSections.includes(s.id))
        .map((section) => {
          const Icon = resolveIcon(section.icon);
          const homeHref = section.items[0]?.href || "/";
          const segs = homeHref.replace(/^\//, "").split("/");
          const seg =
            segs[0] === "integration" && segs[1]
              ? `/${segs[0]}/${segs[1]}`
              : `/${segs[0] || ""}`;
          const active = seg !== "/" && (pathname === seg || pathname.startsWith(seg + "/"));
          return (
            <Link key={section.id} to={homeHref} onClick={closeMobile}>
              <div
                className={cn("sidebar-rail-btn", active && "bg-accent/15")}
                title={section.title}
              >
                <Icon size={18} className={active ? "text-accent" : "text-text-dim"} />
              </div>
            </Link>
          );
        })}
    </>
  );
}

export function Sidebar({ mobile = false }: { mobile?: boolean }) {
  const { pathname } = useLocation();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const { data: bots } = useBots();
  const { data: workspaces } = useWorkspaces();
  const { data: upcomingItems, isLoading: upcomingLoading } = useUpcomingActivity(3);
  const { data: version } = useVersion();
  const { data: sidebarSectionsData } = useSidebarSections();
  const sidebarSections = sidebarSectionsData?.sections || [];
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

          {/* Workspace icon */}
          <Link to={workspaces?.[0] ? `/admin/workspaces/${workspaces[0].id}` : "/admin/workspaces"} onClick={closeMobile}>
            <div
              className={cn("sidebar-rail-btn", pathname.startsWith("/admin/workspaces") && "bg-accent/15")}
              title="Workspaces"
            >
              <Container size={18} className={pathname.startsWith("/admin/workspaces") ? "text-accent" : "text-text-dim"} />
            </div>
          </Link>

          {/* Upcoming icon */}
          <Link to="/admin/upcoming" onClick={closeMobile}>
            <div
              className={cn("sidebar-rail-btn", pathname.startsWith("/admin/upcoming") && "bg-accent/15")}
              title="Upcoming Activity"
            >
              <Clock size={18} className={pathname.startsWith("/admin/upcoming") ? "text-accent" : "text-text-dim"} />
            </div>
          </Link>

          {/* Integration sidebar section icons */}
          <IntegrationRailIcons sections={sidebarSections} pathname={pathname} closeMobile={closeMobile} />

          {/* Divider */}
          <div className="h-px w-5 bg-text-dim/20 my-3" />

          {/* Admin nav icons */}
          {ALL_NAV_ITEMS.map((item) => (
            <RailIcon
              key={item.href}
              item={item}
              active={pathname.startsWith(item.href)}
            />
          ))}
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

        {/* Workspace */}
        {workspaces && workspaces.length > 0 && (() => {
          const ws = workspaces[0];
          return (
            <div className="px-3 pt-4 pb-1">
              <div className="flex flex-row items-center justify-between px-3 mb-1">
                <span className={cn(
                  "font-semibold tracking-wide text-text-dim py-1.5",
                  mobile ? "text-xs" : "text-[11px]",
                )}>
                  WORKSPACE
                </span>
                <Link to={`/admin/workspaces/${ws.id}`} onClick={closeMobile}>
                  <div className="sidebar-icon-btn w-7 h-7 rounded flex flex-row items-center justify-center cursor-pointer">
                    <Settings size={12} className="text-text-dim" />
                  </div>
                </Link>
              </div>
              <div className="mx-1">
                <Link to={`/admin/workspaces/${ws.id}`} onClick={closeMobile}>
                  <div className="sidebar-nav-item flex flex-row items-center gap-2.5 px-3 py-2 cursor-pointer rounded-lg">
                    <span
                      className={cn(
                        "w-2 h-2 rounded-full inline-block shrink-0",
                        ws.status === "running" ? "bg-green-500" : "bg-text-dim",
                      )}
                    />
                    <span className={cn(
                      "flex-1 font-medium text-accent overflow-hidden text-ellipsis whitespace-nowrap",
                      mobile ? "text-[15px]" : "text-sm",
                    )}>
                      {ws.name}
                    </span>
                  </div>
                </Link>
              </div>
            </div>
          );
        })()}

        {/* Upcoming activity */}
        <div className="px-3 pt-4 pb-1">
          <Link to="/admin/upcoming" onClick={closeMobile}>
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
        </div>

        {/* Integration sidebar sections (e.g. Mission Control) */}
        {sidebarSections.map((section) => (
          <IntegrationSidebarSection
            key={section.id}
            section={section}
            pathname={pathname}
            mobile={mobile}
          />
        ))}

        {/* Admin sections */}
        <AdminSections pathname={pathname} mobile={mobile} />
      </div>

      <SidebarFooterExpanded pathname={pathname} mobile={mobile} version={version} />
    </div>
  );
}
