import { View, Text, Pressable, ScrollView } from "react-native";
import { Link, usePathname } from "expo-router";
import {
  MessageSquare,
  Bot,
  BookOpen,
  ClipboardList,
  Wrench,
  FileText,
  ChevronLeft,
  ChevronRight,
  Settings,
  Users,
  Container,
  Plus,
  Hash,
  Home,
  Lock,
  BarChart3,
  Shield,
  ShieldCheck,
  Activity,
  HardDrive,
  Key,
  Code2,
  Server,
  Plug,
  Paperclip,
  Sun,
  Moon,
  Clock,
  Heart,
  LayoutDashboard,
  Columns,
  Brain,
  Layers,
  HelpCircle,
  Zap,
  Filter,
  Mail,
  Camera,
  MessageCircle,
  Terminal,
  Cable,
} from "lucide-react";
import { useMCModules } from "../../api/hooks/useMissionControl";
import { useSidebarSections, useIntegrationIcons, type SidebarSection } from "../../api/hooks/useIntegrations";
import { useUIStore } from "../../stores/ui";
import { useAuthStore } from "../../stores/auth";
import { useThemeStore } from "../../stores/theme";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useWorkspaces } from "../../api/hooks/useWorkspaces";
import { useChannelReadStore } from "../../stores/channelRead";
import { useChatStore } from "../../stores/chat";
import { useShallow } from "zustand/react/shallow";
import { useUpcomingActivity } from "../../api/hooks/useUpcomingActivity";
import { useThemeTokens } from "../../theme/tokens";
import { UsageHudBadge } from "./UsageHudBadge";
import { SpindrelLogo } from "./SpindrelLogo";
import { useVersion } from "../../api/hooks/useVersion";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string }>;
}

/** Resolve a lucide icon name string to a component. Falls back to Plug. */
const ICON_MAP: Record<string, React.ComponentType<{ size: number; color: string }>> = {
  LayoutDashboard, Columns, BookOpen, Brain, HelpCircle, Settings, Zap, Plug, Filter,
  Bot, Layers, FileText, Paperclip, ClipboardList, Key, Shield, ShieldCheck,
  Activity, Server, Wrench, BarChart3, Users, HardDrive, Code2, Hash, Home,
  MessageSquare, Container, Clock, Heart, Lock, Sun, Moon,
  Mail, Camera, MessageCircle, Terminal,
};
function resolveIcon(name: string): React.ComponentType<{ size: number; color: string }> {
  return ICON_MAP[name] || Plug;
}

const ADMIN_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "AGENTS & KNOWLEDGE",
    items: [
      { label: "Bots", href: "/admin/bots", icon: Bot },
      { label: "Carapaces", href: "/admin/carapaces", icon: Layers },
      { label: "Skills", href: "/admin/skills", icon: BookOpen },
      { label: "Tool Index", href: "/admin/tools", icon: Wrench },
      { label: "Templates", href: "/admin/prompt-templates", icon: FileText },
      { label: "Attachments", href: "/admin/attachments", icon: Paperclip },
    ],
  },
  {
    title: "AUTOMATION",
    items: [
      { label: "Tasks", href: "/admin/tasks", icon: ClipboardList },
      { label: "Workflows", href: "/admin/workflows", icon: Zap },
    ],
  },
  {
    title: "SECURITY",
    items: [
      { label: "API Keys", href: "/admin/api-keys", icon: Key },
      { label: "Secrets", href: "/admin/secret-values", icon: Lock },
      { label: "Policies", href: "/admin/tool-policies", icon: Shield },
      { label: "Approvals", href: "/admin/approvals", icon: ShieldCheck },
      { label: "Tool Calls", href: "/admin/tool-calls", icon: Activity },
    ],
  },
  {
    title: "SYSTEM",
    items: [
      { label: "Integrations", href: "/admin/integrations", icon: Plug },
      { label: "Providers", href: "/admin/providers", icon: Server },
      { label: "MCP Servers", href: "/admin/mcp-servers", icon: Cable },
      { label: "Usage", href: "/admin/usage", icon: BarChart3 },
      { label: "Users", href: "/admin/users", icon: Users },
      { label: "Logs", href: "/admin/logs", icon: FileText },
      { label: "Diagnostics", href: "/admin/diagnostics", icon: HardDrive },
      { label: "Config", href: "/admin/config-state", icon: Code2 },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

const ALL_NAV_ITEMS: NavItem[] = ADMIN_SECTIONS.flatMap((s) => s.items);

function NavLink({ item, active, mobile }: { item: NavItem; active: boolean; mobile?: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const t = useThemeTokens();
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`flex-row items-center gap-3 rounded-md px-3 ${mobile ? "py-3" : "py-2"} ${
          active ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
        }`}
      >
        <Icon size={mobile ? 20 : 16} color={active ? t.accent : t.textDim} />
        <Text
          style={mobile ? { fontSize: 15 } : undefined}
          className={`${mobile ? "" : "text-sm"} ${active ? "text-accent font-medium" : "text-text-muted"}`}
          numberOfLines={1}
        >
          {item.label}
        </Text>
      </Pressable>
    </Link>
  );
}

/** Icon-only nav link for collapsed rail */
function RailIcon({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const t = useThemeTokens();
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`items-center justify-center rounded-lg ${
          active ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
        }`}
        style={{ width: 44, height: 44 }}
        accessibilityLabel={item.label}
      >
        <Icon size={18} color={active ? t.accent : t.textDim} />
      </Pressable>
    </Link>
  );
}

/** Skeleton loading rows for channels */
function ChannelSkeletons() {
  const t = useThemeTokens();
  return (
    <View className="gap-1">
      {[1, 2, 3, 4].map((i) => (
        <View key={i} className="flex-row items-center gap-3 px-3 py-2.5">
          <View
            className="rounded animate-pulse"
            style={{ width: 18, height: 18, backgroundColor: t.skeletonBg }}
          />
          <View className="flex-1 gap-1.5">
            <View
              className="rounded animate-pulse"
              style={{
                height: 13,
                width: `${50 + i * 10}%`,
                backgroundColor: t.skeletonBg,
              }}
            />
            <View
              className="rounded animate-pulse"
              style={{
                height: 10,
                width: `${30 + i * 8}%`,
                backgroundColor: t.skeletonBg,
              }}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

/** Collapsed rail: icon-only theme toggle */
function ThemeToggleIcon() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={toggle}
      className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
      style={{ width: 44, height: 44 }}
      accessibilityLabel="Toggle theme"
    >
      {mode === "dark" ? <Sun size={16} color={t.textDim} /> : <Moon size={16} color={t.textDim} />}
    </Pressable>
  );
}

/** Expanded sidebar: full row with label */
function ThemeToggleRow() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={toggle}
      className="flex-row items-center gap-3 rounded-md px-3 py-2 hover:bg-surface-overlay active:bg-surface-overlay"
    >
      {mode === "dark" ? <Sun size={16} color={t.textDim} /> : <Moon size={16} color={t.textDim} />}
      <Text className="text-sm text-text-muted">
        {mode === "dark" ? "Light mode" : "Dark mode"}
      </Text>
    </Pressable>
  );
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

  if (hiddenSections.includes(section.id)) return null;

  // Resolve items from the API-declared section
  const items: NavItem[] = section.items.map((item) => ({
    label: item.label,
    href: item.href,
    icon: resolveIcon(item.icon),
  }));

  // Append dashboard modules belonging to this section's integration
  const modules = (modulesData?.modules || []).filter(
    (m) => m.integration_id === section.integration_id,
  );

  // Determine the section's URL prefix from first item
  // For /integration/{id}/... paths, use first two segments as prefix
  const sectionHome = items[0]?.href || "/";
  const segments = sectionHome.replace(/^\//, "").split("/");
  const sectionPrefix =
    segments[0] === "integration" && segments[1]
      ? `/${segments[0]}/${segments[1]}`
      : `/${segments[0] || ""}`;
  const isInSection = sectionPrefix !== "/" && (pathname === sectionPrefix || pathname.startsWith(sectionPrefix + "/"));

  return (
    <View className="px-2 py-1.5">
      <Text className={`text-text-dim ${mobile ? "text-xs" : "text-[11px]"} font-semibold tracking-wider px-3 py-1.5`}>
        {section.title}
      </Text>
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
    </View>
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
            <Link key={section.id} href={homeHref as any} asChild>
              <Pressable
                onPress={closeMobile}
                className={`items-center justify-center rounded-lg ${
                  active ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
                }`}
                style={{ width: 44, height: 44 }}
                accessibilityLabel={section.title}
              >
                <Icon size={18} color={active ? t.accent : t.textDim} />
              </Pressable>
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
  const user = useAuthStore((s) => s.user);
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const { data: bots } = useBots();
  const { data: workspaces, isLoading: workspacesLoading } = useWorkspaces();
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

  // Orchestrator channel — always included by server regardless of workspace filter
  const orchestratorChannel = channels?.find((ch) => ch.client_id === "orchestrator:home");
  // Regular channels exclude orchestrator
  const regularChannels = channels?.filter((ch) => ch.client_id !== "orchestrator:home") ?? [];

  // -----------------------------------------------------------------------
  // Collapsed: icon rail (56px)
  // -----------------------------------------------------------------------
  if (collapsed) {
    return (
      <View className="bg-surface border-r border-surface-border items-center" style={{ width: 56, flexShrink: 0, height: '100%' }}>
        <ScrollView className="flex-1" showsVerticalScrollIndicator={false} contentContainerStyle={{ alignItems: "center", paddingTop: 10, paddingBottom: 10, gap: 2 }}>
          {/* Logo */}
          <View className="items-center justify-center" style={{ width: 44, height: 36 }}>
            <SpindrelLogo size={22} color={t.text} />
          </View>

          {/* Expand toggle */}
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
            accessibilityLabel="Expand sidebar"
          >
            <ChevronRight size={16} color={t.textDim} />
          </Pressable>

          {/* Home (orchestrator) icon */}
          {orchestratorChannel && (() => {
            const orchActive = pathname.includes(orchestratorChannel.id);
            return (
              <Link href={`/channels/${orchestratorChannel.id}` as any} asChild>
                <Pressable
                  onPress={closeMobile}
                  className={`items-center justify-center rounded-lg ${
                    orchActive ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
                  }`}
                  style={{ width: 44, height: 44 }}
                  accessibilityLabel="Home"
                >
                  <Home size={18} color={orchActive ? t.accent : t.textDim} />
                </Pressable>
              </Link>
            );
          })()}

          {/* Channels icon */}
          <Link href="/" asChild>
            <Pressable
              onPress={closeMobile}
              className={`items-center justify-center rounded-lg ${
                pathname === "/" ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
              }`}
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Channels"
            >
              <View>
                <MessageSquare size={18} color={pathname === "/" ? t.accent : t.textDim} />
                {channels?.filter((ch) => ch.client_id !== "orchestrator:home").some((ch) => !pathname.includes(ch.id) && isUnread(ch.id, ch.updated_at)) && (
                  <View
                    style={{
                      position: "absolute",
                      top: -2,
                      right: -2,
                      width: 7,
                      height: 7,
                      borderRadius: 4,
                      backgroundColor: t.accent,
                    }}
                  />
                )}
              </View>
            </Pressable>
          </Link>

          {/* Workspace icon */}
          <Link href={workspaces?.[0] ? `/admin/workspaces/${workspaces[0].id}` as any : "/admin/workspaces" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className={`items-center justify-center rounded-lg ${
                pathname.startsWith("/admin/workspaces") ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
              }`}
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Workspaces"
            >
              <Container size={18} color={pathname.startsWith("/admin/workspaces") ? t.accent : t.textDim} />
            </Pressable>
          </Link>

          {/* Upcoming icon */}
          <Link href={"/admin/upcoming" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className={`items-center justify-center rounded-lg ${
                pathname.startsWith("/admin/upcoming") ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
              }`}
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Upcoming Activity"
            >
              <Clock size={18} color={pathname.startsWith("/admin/upcoming") ? t.accent : t.textDim} />
            </Pressable>
          </Link>

          {/* Integration sidebar section icons */}
          <IntegrationRailIcons sections={sidebarSections} pathname={pathname} closeMobile={closeMobile} t={t} />

          {/* Divider */}
          <View className="bg-surface-border my-1.5" style={{ height: 1, width: 32 }} />

          {/* Admin nav icons */}
          {ALL_NAV_ITEMS.map((item) => (
            <RailIcon
              key={item.href}
              item={item}
              active={pathname.startsWith(item.href)}
            />
          ))}
        </ScrollView>

        {/* Footer icons */}
        <View className="border-t border-surface-border items-center py-2.5 gap-1">
          <UsageHudBadge collapsed />
          <ThemeToggleIcon />
          <Link href={"/(app)/profile" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className="items-center justify-center rounded-lg hover:bg-surface-overlay active:bg-surface-overlay"
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Profile"
            >
              <View className="w-7 h-7 rounded items-center justify-center" style={{ backgroundColor: "rgba(99,102,241,0.2)" }}>
                <Text style={{ fontSize: 11, color: "#6366f1", fontWeight: "700" }}>
                  {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
                </Text>
              </View>
            </Pressable>
          </Link>
          {version && (
            <Text className="text-text-dim" style={{ fontSize: 9, opacity: 0.6 }}>
              v{version}
            </Text>
          )}
        </View>
      </View>
    );
  }

  // -----------------------------------------------------------------------
  // Expanded sidebar (260px desktop, flex on mobile)
  // -----------------------------------------------------------------------
  const channelPy = mobile ? "py-3" : "py-2";

  return (
    <View className="bg-surface border-r border-surface-border" style={{ width: mobile ? "100%" : 260, flexShrink: 0, height: '100%' }}>
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 8 }}>
        {/* Header */}
        <View className="flex-row items-center justify-between px-4 py-4">
          <Link href="/" asChild>
            <Pressable className="flex-row items-center gap-2">
              <SpindrelLogo size={22} color={t.text} />
              <Text style={{ fontSize: 15, fontWeight: "700", letterSpacing: 1.5, color: t.text }}>SPINDREL</Text>
            </Pressable>
          </Link>
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded hover:bg-surface-overlay active:bg-surface-overlay"
            style={{ width: 32, height: 32 }}
          >
            <ChevronLeft size={16} color={t.textDim} />
          </Pressable>
        </View>

        {/* Home (orchestrator) — always visible */}
        {!channelsLoading && orchestratorChannel && (() => {
          const channel = orchestratorChannel;
          const isActive = pathname.includes(channel.id);
          const unread = !isActive && isUnread(channel.id, channel.updated_at);
          return (
            <View className="px-2 pt-1.5 pb-0.5">
              <Link key={channel.id} href={`/channels/${channel.id}` as any} asChild>
                <Pressable
                  onPress={closeMobile}
                  className={`flex-row items-center gap-2.5 rounded-lg px-3 ${channelPy} ${
                    isActive ? "bg-accent/15" : "hover:bg-surface-overlay active:bg-surface-overlay"
                  }`}
                  style={!isActive ? { backgroundColor: t.accent + "08" } : undefined}
                >
                  <Home size={mobile ? 20 : 16} color={isActive ? t.accent : t.text} />
                  <Text
                    style={mobile ? { fontSize: 15 } : undefined}
                    className={`flex-1 ${mobile ? "" : "text-sm"} ${
                      isActive ? "text-accent font-medium" : unread ? "text-text font-semibold" : "text-text font-medium"
                    }`}
                    numberOfLines={1}
                  >
                    Orchestrator
                  </Text>
                  <Shield size={12} color={t.textDim} style={{ opacity: 0.6, flexShrink: 0 }} />
                  {unread && (
                    <View
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: 4,
                        backgroundColor: t.accent,
                        flexShrink: 0,
                      }}
                    />
                  )}
                </Pressable>
              </Link>
            </View>
          );
        })()}

        {/* Channels */}
        <View className="px-2 py-1.5">
          <View className="flex-row items-center justify-between px-3 mb-1">
            <Text className="text-text-dim text-[11px] font-semibold tracking-wider py-1.5">
              CHANNELS
            </Text>
            <Link href={"/channels/new" as any} asChild>
              <Pressable
                onPress={closeMobile}
                className="items-center justify-center rounded hover:bg-surface-overlay active:bg-surface-overlay"
                style={{ width: 28, height: 28 }}
              >
                <Plus size={14} color={t.textDim} />
              </Pressable>
            </Link>
          </View>

          {channelsLoading ? (
            <ChannelSkeletons />
          ) : (
            <>
              {/* Regular channels */}
              {regularChannels.map((channel) => {
                const bot = botMap.get(channel.bot_id);
                const isActive = pathname.includes(channel.id);
                const unread = !isActive && isUnread(channel.id, channel.updated_at);
                const displayName = channel.display_name || channel.name || channel.client_id;
                return (
                  <Link
                    key={channel.id}
                    href={`/channels/${channel.id}` as any}
                    asChild
                  >
                    <Pressable
                      onPress={closeMobile}
                      className={`flex-row items-center gap-2.5 rounded-md px-3 ${channelPy} ${
                        isActive ? "bg-accent/10" : "hover:bg-surface-overlay active:bg-surface-overlay"
                      }`}
                    >
                      {channel.private ? (
                        <Lock size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
                      ) : (
                        <Hash size={mobile ? 20 : 16} color={isActive ? t.accent : t.textDim} />
                      )}
                      <View className="flex-1 min-w-0">
                        <Text
                          style={mobile ? { fontSize: 15 } : undefined}
                          className={`${mobile ? "" : "text-sm"} ${
                            isActive ? "text-accent font-medium" : unread ? "text-text font-semibold" : "text-text-muted"
                          }`}
                          numberOfLines={1}
                        >
                          {displayName}
                        </Text>
                        {bot && (
                          <View className="flex-row items-center gap-1">
                            <Text className={`${mobile ? "text-xs" : "text-[11px]"} text-text-dim`} numberOfLines={1}>
                              {bot.name}
                            </Text>
                            {channel.channel_workspace_enabled && (
                              <Container size={11} color={t.textDim} style={{ opacity: 0.5 }} />
                            )}
                            {channel.integrations?.map((binding) => {
                              const IIcon = resolveIcon(integrationIcons[binding.integration_type] || "Plug");
                              return <View key={binding.id} style={{ opacity: 0.6 }}><IIcon size={11} color={t.textDim} /></View>;
                            })}
                          </View>
                        )}
                        {channel.tags && channel.tags.length > 0 && (
                          <Text className="text-[10px] text-text-dim" numberOfLines={1} style={{ opacity: 0.6 }}>
                            {channel.tags.slice(0, 2).join(", ")}
                          </Text>
                        )}
                      </View>
                      {streamingSet.has(channel.id) && (
                        <View
                          className="animate-pulse"
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: 4,
                            backgroundColor: t.accent,
                            flexShrink: 0,
                          }}
                        />
                      )}
                      {channel.heartbeat_enabled && !channel.heartbeat_in_quiet_hours && !streamingSet.has(channel.id) && (
                        <View
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: 3,
                            backgroundColor: "#22c55e",
                            flexShrink: 0,
                            opacity: 0.8,
                          }}
                        />
                      )}
                      {channel.heartbeat_in_quiet_hours && !streamingSet.has(channel.id) && (
                        <Moon size={12} color={t.textDim} style={{ flexShrink: 0, opacity: 0.5 }} />
                      )}
                      {unread && !streamingSet.has(channel.id) && (
                        <View
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: 4,
                            backgroundColor: t.accent,
                            flexShrink: 0,
                          }}
                        />
                      )}
                    </Pressable>
                  </Link>
                );
              })}
              {regularChannels.length === 0 && (
                <Text className="text-text-dim text-xs px-3 py-2">No channels yet</Text>
              )}
            </>
          )}
        </View>

        {/* Workspace */}
        {workspaces && workspaces.length > 0 && (() => {
          const ws = workspaces[0];
          return (
            <View className="px-2 py-1.5">
              <View className="flex-row items-center justify-between px-3 mb-1">
                <Text className={`text-text-dim ${mobile ? "text-xs" : "text-[11px]"} font-semibold tracking-wider py-1.5`}>
                  WORKSPACE
                </Text>
                <Link href={`/admin/workspaces/${ws.id}` as any} asChild>
                  <Pressable
                    onPress={closeMobile}
                    className="items-center justify-center rounded hover:bg-surface-overlay active:bg-surface-overlay"
                    style={{ width: 28, height: 28 }}
                  >
                    <Settings size={12} color={t.textDim} />
                  </Pressable>
                </Link>
              </View>
              <View className="flex-row items-center rounded-lg border border-surface-border overflow-hidden" style={{ marginHorizontal: 4 }}>
                <Link href={`/admin/workspaces/${ws.id}/files` as any} asChild>
                  <Pressable
                    onPress={closeMobile}
                    className="flex-1 flex-row items-center gap-2.5 px-3 hover:bg-surface-overlay active:bg-surface-overlay"
                    style={{ paddingVertical: 8 }}
                  >
                    <View style={{
                      width: 8, height: 8, borderRadius: 4,
                      backgroundColor: ws.status === "running" ? "#22c55e" : t.textDim,
                    }} />
                    <Text
                      style={mobile ? { fontSize: 15 } : undefined}
                      className={`flex-1 ${mobile ? "" : "text-sm"} text-accent font-medium`}
                      numberOfLines={1}
                    >
                      {ws.name}
                    </Text>
                  </Pressable>
                </Link>
              </View>
            </View>
          );
        })()}

        {/* Upcoming activity */}
        <View className="px-2 py-1.5">
          <Link href={"/admin/upcoming" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className="flex-row items-center justify-between px-3 mb-1 rounded hover:bg-surface-overlay active:bg-surface-overlay"
            >
              <Text className="text-text-dim text-[11px] font-semibold tracking-wider py-1.5">
                UPCOMING
              </Text>
              <Clock size={12} color={t.textDim} />
            </Pressable>
          </Link>

          {upcomingLoading ? (
            <View className="gap-1">
              {[1, 2].map((i) => (
                <View key={i} className="flex-row items-center gap-2.5 px-3 py-1.5">
                  <View
                    className="rounded animate-pulse"
                    style={{ width: 14, height: 14, backgroundColor: t.skeletonBg }}
                  />
                  <View className="flex-1 gap-1">
                    <View
                      className="rounded animate-pulse"
                      style={{ height: 12, width: `${50 + i * 15}%`, backgroundColor: t.skeletonBg }}
                    />
                  </View>
                </View>
              ))}
            </View>
          ) : !upcomingItems?.length ? (
            <Text className="text-text-dim text-xs px-3 py-1">No upcoming activity</Text>
          ) : (
            upcomingItems.map((item, idx) => {
              const href = item.type === "heartbeat" && item.channel_id
                ? `/channels/${item.channel_id}/settings#heartbeat`
                : "/admin/tasks";
              return (
                <Link key={`${item.type}-${idx}`} href={href as any} asChild>
                  <Pressable
                    onPress={closeMobile}
                    className="flex-row items-center gap-2 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
                  >
                    {item.type === "heartbeat" ? (
                      <Heart size={13} color={item.in_quiet_hours ? t.textDim : t.warning} style={item.in_quiet_hours ? { opacity: 0.4 } : undefined} />
                    ) : (
                      <ClipboardList size={13} color={t.accent} />
                    )}
                    <View
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: 3,
                        backgroundColor: botDotColor(item.bot_id),
                        flexShrink: 0,
                      }}
                    />
                    <Text className="text-text-muted text-xs flex-1" numberOfLines={1}>
                      {item.type === "heartbeat" && item.channel_name ? `#${item.channel_name}` : item.title}
                    </Text>
                    <Text className="text-text-dim text-[10px]" style={{ flexShrink: 0 }}>
                      {item.scheduled_at ? relativeTime(item.scheduled_at) : ""}
                    </Text>
                  </Pressable>
                </Link>
              );
            })
          )}
        </View>

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
        {ADMIN_SECTIONS.map((section) => (
          <View key={section.title} className="px-2 py-1.5">
            <Text className={`text-text-dim ${mobile ? "text-xs" : "text-[11px]"} font-semibold tracking-wider px-3 py-1.5`}>
              {section.title}
            </Text>
            {section.items.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={pathname.startsWith(item.href)}
                mobile={mobile}
              />
            ))}
          </View>
        ))}
      </ScrollView>

      {/* Footer — theme toggle + profile */}
      <View className="border-t border-surface-border p-2.5 gap-0.5">
        <UsageHudBadge collapsed={false} />
        <ThemeToggleRow />
        <Link href={"/(app)/profile" as any} asChild>
          <Pressable
            onPress={closeMobile}
            className={`flex-row items-center gap-3 rounded-md px-3 ${mobile ? "py-3.5" : "py-2.5"} ${
              pathname === "/profile" ? "bg-accent/10" : "hover:bg-surface-overlay active:bg-surface-overlay"
            }`}
          >
            <View className={`${mobile ? "w-9 h-9" : "w-8 h-8"} rounded items-center justify-center`} style={{ backgroundColor: "rgba(99,102,241,0.2)" }}>
              <Text style={{ fontSize: mobile ? 14 : 12, color: "#6366f1", fontWeight: "700" }}>
                {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
              </Text>
            </View>
            <Text
              style={mobile ? { fontSize: 15 } : undefined}
              className={`${mobile ? "" : "text-sm"} flex-1 ${
                pathname === "/profile" ? "text-accent font-medium" : "text-text-muted"
              }`}
              numberOfLines={1}
            >
              {user?.display_name || "Profile"}
            </Text>
          </Pressable>
        </Link>
        {version && (
          <Text className="text-text-dim text-center" style={{ fontSize: 10, opacity: 0.5 }}>
            v{version}
          </Text>
        )}
      </View>
    </View>
  );
}
