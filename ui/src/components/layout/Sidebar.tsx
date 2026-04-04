import { useState } from "react";
import { Link, usePathname } from "expo-router";
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
  Cable,
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
import { useThemeTokens } from "../../theme/tokens";
import { SpindrelLogo } from "./SpindrelLogo";
import { useVersion } from "../../api/hooks/useVersion";

// Sub-components
import { ChannelList } from "./sidebar/ChannelList";
import { ALL_NAV_ITEMS, AdminSections, NavLink, RailIcon } from "./sidebar/AdminNav";
import { ThemeToggleIcon, SidebarFooterCollapsed, SidebarFooterExpanded } from "./sidebar/SidebarFooter";

/** Resolve a lucide icon name string to a component. Falls back to Plug. */
const ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  LayoutDashboard, Columns, BookOpen, Brain, HelpCircle, Settings, Zap, Plug, Filter,
  Bot, Layers, FileText, Paperclip, ClipboardCheck, ClipboardList, Key, Shield, ShieldCheck,
  Activity, Server, Wrench, BarChart3, Users, HardDrive, Code2, Hash, Home,
  MessageSquare, Container, Clock, Heart, Lock, Sun, Moon,
  Mail, Camera, MessageCircle, Terminal,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; color: string }> {
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
  const t = useThemeTokens();
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
    <div style={{ padding: "6px 8px" }}>
      <button
        onClick={toggle}
        className="sidebar-nav-item"
        style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "6px 12px", borderRadius: 4,
          background: "none", border: "none", cursor: "pointer",
          width: "100%", textAlign: "left",
        }}
      >
        <SectionIcon size={12} color={hasActive ? t.accent : t.textDim} />
        <span style={{
          flex: 1,
          fontSize: mobile ? 12 : 11, fontWeight: 600,
          letterSpacing: 0.5,
          color: hasActive ? t.accent : t.textDim,
        }}>
          {section.title}
        </span>
        <ChevronRight
          size={10}
          color={t.textDim}
          style={{
            transform: collapsed ? "rotate(0deg)" : "rotate(90deg)",
            transition: "transform 0.15s",
          }}
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
  t,
}: {
  sections: SidebarSection[];
  pathname: string;
  closeMobile: () => void;
  t: ReturnType<typeof useThemeTokens>;
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
            <Link key={section.id} href={homeHref as any} onPress={closeMobile}>
              <div
                className="sidebar-icon-btn"
                title={section.title}
                style={{
                  width: 44, height: 44, borderRadius: 8,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer",
                  backgroundColor: active ? "rgba(59,130,246,0.15)" : undefined,
                }}
              >
                <Icon size={18} color={active ? t.accent : t.textDim} />
              </div>
            </Link>
          );
        })}
    </>
  );
}

export function Sidebar({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
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
  const t = useThemeTokens();
  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);
  const isUnread = useChannelReadStore((s) => s.isUnread);
  const streamingChannelIds = useChatStore(
    useShallow((s) =>
      Object.entries(s.channels)
        .filter(([, ch]) => ch.isStreaming)
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
      <div style={{
        width: 56, flexShrink: 0, height: "100%",
        display: "flex", flexDirection: "column",
        alignItems: "center",
        backgroundColor: t.surface,
        borderRight: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          flex: 1, overflowY: "auto", overflowX: "hidden",
          display: "flex", flexDirection: "column", alignItems: "center",
          paddingTop: 10, paddingBottom: 10, gap: 2,
        }}>
          {/* Logo */}
          <div style={{ width: 44, height: 36, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <SpindrelLogo size={22} color={t.text} />
          </div>

          {/* Expand toggle */}
          <button
            onClick={toggleSidebar}
            className="sidebar-icon-btn"
            style={{
              width: 44, height: 44, borderRadius: 8,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "none", border: "none", cursor: "pointer", padding: 0,
            }}
            aria-label="Expand sidebar"
          >
            <ChevronRight size={16} color={t.textDim} />
          </button>

          {/* Home (orchestrator) icon */}
          {orchestratorChannel && (() => {
            const orchActive = pathname.includes(orchestratorChannel.id);
            return (
              <Link href={`/channels/${orchestratorChannel.id}` as any} onPress={closeMobile}>
                <div
                  className="sidebar-icon-btn"
                  title="Home"
                  style={{
                    width: 44, height: 44, borderRadius: 8,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    cursor: "pointer",
                    backgroundColor: orchActive ? "rgba(59,130,246,0.15)" : undefined,
                  }}
                >
                  <Home size={18} color={orchActive ? t.accent : t.textDim} />
                </div>
              </Link>
            );
          })()}

          {/* Channels icon */}
          <Link href={"/" as any} onPress={closeMobile}>
            <div
              className="sidebar-icon-btn"
              title="Channels"
              style={{
                width: 44, height: 44, borderRadius: 8,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
                backgroundColor: pathname === "/" ? "rgba(59,130,246,0.15)" : undefined,
              }}
            >
              <div style={{ position: "relative" }}>
                <MessageSquare size={18} color={pathname === "/" ? t.accent : t.textDim} />
                {channels?.filter((ch) => ch.client_id !== "orchestrator:home").some((ch) => !pathname.includes(ch.id) && isUnread(ch.id, ch.updated_at)) && (
                  <span style={{
                    position: "absolute", top: -2, right: -2,
                    width: 7, height: 7, borderRadius: 4,
                    backgroundColor: t.accent, display: "inline-block",
                  }} />
                )}
              </div>
            </div>
          </Link>

          {/* Workspace icon */}
          <Link href={(workspaces?.[0] ? `/admin/workspaces/${workspaces[0].id}` : "/admin/workspaces") as any} onPress={closeMobile}>
            <div
              className="sidebar-icon-btn"
              title="Workspaces"
              style={{
                width: 44, height: 44, borderRadius: 8,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
                backgroundColor: pathname.startsWith("/admin/workspaces") ? "rgba(59,130,246,0.15)" : undefined,
              }}
            >
              <Container size={18} color={pathname.startsWith("/admin/workspaces") ? t.accent : t.textDim} />
            </div>
          </Link>

          {/* Upcoming icon */}
          <Link href={"/admin/upcoming" as any} onPress={closeMobile}>
            <div
              className="sidebar-icon-btn"
              title="Upcoming Activity"
              style={{
                width: 44, height: 44, borderRadius: 8,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
                backgroundColor: pathname.startsWith("/admin/upcoming") ? "rgba(59,130,246,0.15)" : undefined,
              }}
            >
              <Clock size={18} color={pathname.startsWith("/admin/upcoming") ? t.accent : t.textDim} />
            </div>
          </Link>

          {/* Integration sidebar section icons */}
          <IntegrationRailIcons sections={sidebarSections} pathname={pathname} closeMobile={closeMobile} t={t} />

          {/* Divider */}
          <div style={{ height: 1, width: 32, backgroundColor: t.surfaceBorder, margin: "6px 0" }} />

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
  const channelPy = mobile ? "py-3" : "py-2";

  return (
    <div style={{
      width: mobile ? "100%" : 260, flexShrink: 0, height: "100%",
      display: "flex", flexDirection: "column",
      backgroundColor: t.surface,
      borderRight: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{ flex: 1, overflowY: "auto", overflowX: "hidden", paddingBottom: 8 }}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "16px 16px",
        }}>
          <Link href={"/" as any}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
              <SpindrelLogo size={22} color={t.text} />
              <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: 1.5, color: t.text }}>SPINDREL</span>
            </div>
          </Link>
          <button
            onClick={toggleSidebar}
            className="sidebar-icon-btn"
            style={{
              width: 32, height: 32, borderRadius: 4,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "none", border: "none", cursor: "pointer", padding: 0,
            }}
          >
            <ChevronLeft size={16} color={t.textDim} />
          </button>
        </div>

        {/* Channel list (orchestrator + regular channels with category grouping) */}
        <ChannelList
          channels={channels}
          channelsLoading={channelsLoading}
          botMap={botMap}
          integrationIcons={integrationIcons}
          mobile={mobile}
          channelPy={channelPy}
          streamingSet={streamingSet}
        />

        {/* Workspace */}
        {workspaces && workspaces.length > 0 && (() => {
          const ws = workspaces[0];
          return (
            <div style={{ padding: "6px 8px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 12px", marginBottom: 4 }}>
                <span style={{ fontSize: mobile ? 12 : 11, fontWeight: 600, letterSpacing: 0.5, color: t.textDim, padding: "6px 0" }}>
                  WORKSPACE
                </span>
                <Link href={`/admin/workspaces/${ws.id}` as any} onPress={closeMobile}>
                  <div
                    className="sidebar-icon-btn"
                    style={{
                      width: 28, height: 28, borderRadius: 4,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      cursor: "pointer",
                    }}
                  >
                    <Settings size={12} color={t.textDim} />
                  </div>
                </Link>
              </div>
              <div style={{
                display: "flex", alignItems: "center",
                borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
                overflow: "hidden", margin: "0 4px",
              }}>
                <Link href={`/admin/workspaces/${ws.id}/files` as any} onPress={closeMobile}>
                  <div
                    className="sidebar-nav-item"
                    style={{
                      flex: 1, display: "flex", alignItems: "center", gap: 10,
                      padding: "8px 12px", cursor: "pointer",
                    }}
                  >
                    <span style={{
                      width: 8, height: 8, borderRadius: 4,
                      backgroundColor: ws.status === "running" ? "#22c55e" : t.textDim,
                      display: "inline-block", flexShrink: 0,
                    }} />
                    <span style={{
                      flex: 1, fontSize: mobile ? 15 : 14,
                      color: t.accent, fontWeight: 500,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {ws.name}
                    </span>
                  </div>
                </Link>
              </div>
            </div>
          );
        })()}

        {/* Upcoming activity */}
        <div style={{ padding: "6px 8px" }}>
          <Link href={"/admin/upcoming" as any} onPress={closeMobile}>
            <div
              className="sidebar-nav-item"
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "0 12px", marginBottom: 4, borderRadius: 4, cursor: "pointer",
              }}
            >
              <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.5, color: t.textDim, padding: "6px 0" }}>
                UPCOMING
              </span>
              <Clock size={12} color={t.textDim} />
            </div>
          </Link>

          {upcomingLoading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {[1, 2].map((i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 12px" }}>
                  <div style={{
                    width: 14, height: 14, borderRadius: 4,
                    backgroundColor: t.skeletonBg,
                    animation: "pulse 2s ease-in-out infinite",
                  }} />
                  <div style={{ flex: 1 }}>
                    <div style={{
                      height: 12, width: `${50 + i * 15}%`, borderRadius: 4,
                      backgroundColor: t.skeletonBg,
                      animation: "pulse 2s ease-in-out infinite",
                    }} />
                  </div>
                </div>
              ))}
            </div>
          ) : !upcomingItems?.length ? (
            <span style={{ fontSize: 12, color: t.textDim, padding: "4px 12px", display: "block" }}>
              No upcoming activity
            </span>
          ) : (
            upcomingItems.map((item, idx) => {
              const href = item.type === "heartbeat" && item.channel_id
                ? `/channels/${item.channel_id}/settings#heartbeat`
                : "/admin/tasks";
              return (
                <Link key={`${item.type}-${idx}`} href={href as any} onPress={closeMobile}>
                  <div
                    className="sidebar-nav-item"
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      borderRadius: 6, padding: "6px 12px", cursor: "pointer",
                    }}
                  >
                    {item.type === "heartbeat" ? (
                      <Heart size={13} color={item.in_quiet_hours ? t.textDim : t.warning} style={item.in_quiet_hours ? { opacity: 0.4 } : undefined} />
                    ) : (
                      <ClipboardList size={13} color={t.accent} />
                    )}
                    <span style={{
                      width: 6, height: 6, borderRadius: 3,
                      backgroundColor: botDotColor(item.bot_id),
                      flexShrink: 0, display: "inline-block",
                    }} />
                    <span style={{
                      flex: 1, fontSize: 12, color: t.textMuted,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {item.type === "heartbeat" && item.channel_name ? `#${item.channel_name}` : item.title}
                    </span>
                    <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
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
