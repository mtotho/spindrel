import { Link, useLocation } from "react-router-dom";
import {
  Clock,
  BarChart3,
  Brain,
  Bot,
  BookOpen,
  FolderKanban,
  Hash,
  Inbox,
  Monitor,
  Plug,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { SpindrelLogo } from "../SpindrelLogo";
import { useUIStore } from "../../../stores/ui";
import { useAuthStore } from "../../../stores/auth";
import { useIsAdmin } from "../../../hooks/useScope";
import { useThemeStore } from "../../../stores/theme";
import { useVersion } from "../../../api/hooks/useVersion";
import { useProjectFactoryReviewInbox } from "../../../api/hooks/useProjects";
import { useLatestHealthSummary } from "../../../api/hooks/useSystemHealth";
import { useWorkspaceAttention, useWorkspaceAttentionBrief } from "../../../api/hooks/useWorkspaceAttention";
import { useUnreadState } from "../../../api/hooks/useUnread";
import {
  channelIdFromSlug,
  isChannelSlug,
  isWorkspaceSpatialSlug,
  useDashboards,
} from "../../../stores/dashboards";
import { useChannels } from "../../../api/hooks/useChannels";
import { useChannelReadStore } from "../../../stores/channelRead";
import { LucideIconByName } from "../../IconPicker";
import { cn } from "../../../lib/cn";
import { buildActionInboxModel } from "../../../lib/actionInbox";
import { useTodayUpcomingCount } from "./UpcomingRailPopover";
import { AvatarMenu } from "./AvatarMenu";

interface RailLinkProps {
  href: string;
  active?: boolean;
  title: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
  /**
   * Pinned user content (e.g. a widget dashboard) rather than a top-level app
   * section. Gets a subtle inset ring so it scans as "bookmark / your stuff"
   * instead of blending into the nav icons around it.
   */
  pinned?: boolean;
}

function RailLink({ href, active, title, children, badge, pinned }: RailLinkProps) {
  return (
    <Link
      to={href}
      title={title}
      aria-label={title}
      aria-current={active ? "page" : undefined}
      className={cn(
        "sidebar-rail-btn relative bg-transparent border-none p-0",
        pinned && !active && "ring-1 ring-inset ring-surface-border/50 hover:ring-surface-border/80",
        active &&
          "bg-accent/[0.12] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-4 before:rounded-full before:bg-accent",
      )}
    >
      {children}
      {badge}
    </Link>
  );
}

interface RailButtonProps {
  active?: boolean;
  title: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
  onClick: () => void;
}

function RailButton({ active, title, children, badge, onClick }: RailButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={cn(
        "sidebar-rail-btn relative bg-transparent border-none p-0",
        active &&
          "bg-accent/[0.12] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-4 before:rounded-full before:bg-accent",
      )}
    >
      {children}
      {badge}
    </button>
  );
}

interface SidebarRailProps {
  unreadInboxOpen?: boolean;
  onToggleUnreadInbox?: () => void;
}

export function SidebarRail({ unreadInboxOpen = false, onToggleUnreadInbox }: SidebarRailProps) {
  const { pathname, search } = useLocation();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const user = useAuthStore((s) => s.user);
  const isAdmin = useIsAdmin();
  const themeMode = useThemeStore((s) => s.mode);
  const toggleTheme = useThemeStore((s) => s.toggle);
  const { data: version } = useVersion();
  const upcomingCount = useTodayUpcomingCount();
  const { data: unreadState } = useUnreadState();
  const { data: attention } = useWorkspaceAttention();
  const { data: attentionBrief } = useWorkspaceAttentionBrief();
  const { data: health } = useLatestHealthSummary();
  const { data: projectReviewInbox } = useProjectFactoryReviewInbox(8);
  const { data: workPacks = [] } = useIssueWorkPacks();
  const unreadTotal = useChannelReadStore((s) =>
    Object.values(s.unreadByChannel).reduce((sum, count) => sum + count, 0),
  );
  const inboxTotal = buildActionInboxModel({
    unreadStates: unreadState?.states,
    attentionItems: attention,
    attentionBrief,
    health,
    projectReviewInbox,
    workPacks,
  }).total || unreadTotal;
  // `allDashboards` includes channel-scoped dashboards (slug prefix `channel:`)
  // so a user can opt to pin a channel dashboard to the rail like any other.
  const { allDashboards } = useDashboards();
  const { data: channels } = useChannels();
  const channelNameById = useMemo(() => {
    const m = new Map<string, string>();
    if (!channels) return m;
    for (const c of channels) m.set(c.id, c.name);
    return m;
  }, [channels]);
  const railDashboards = allDashboards
    .filter((d) => !isWorkspaceSpatialSlug(d.slug))
    .filter((d) => d.rail.me_pinned || d.rail.everyone_pinned)
    .sort((a, b) => {
      const ap = a.rail.effective_position ?? Number.MAX_SAFE_INTEGER;
      const bp = b.rail.effective_position ?? Number.MAX_SAFE_INTEGER;
      if (ap !== bp) return ap - bp;
      return a.name.localeCompare(b.name);
    });

  const isTasksActive = pathname.startsWith("/admin/automations");
  const isBotsActive = pathname.startsWith("/admin/bots");
  const isSkillsActive = pathname.startsWith("/admin/skills");
  const isIntegrationsActive = pathname.startsWith("/admin/integrations");
  const isMachinesActive = pathname.startsWith("/admin/machines");
  const isUsageActive = pathname.startsWith("/admin/usage");
  const isLearningActive = pathname.startsWith("/admin/learning");
  const isProjectsActive = pathname.startsWith("/admin/projects");
  const isHomeActive = pathname === "/" && !search;

  const [avatarOpen, setAvatarOpen] = useState(false);
  const avatarBtnRef = useRef<HTMLButtonElement>(null);

  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  const modKey = isMac ? "\u2318" : "Ctrl";

  const PanelToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;

  return (
    <div className="w-12 shrink-0 h-full flex flex-col items-center bg-surface border-r border-surface-border/60">
      {/* Top cluster */}
      <div className="flex flex-col items-center gap-1 pt-2.5">
        <Link
          to="/"
          title={version ? `Home  ·  Spindrel v${version}` : "Home"}
          aria-label="Home"
          aria-current={isHomeActive ? "page" : undefined}
          className={cn(
            "w-10 h-10 relative flex flex-row items-center justify-center text-text rounded-md",
            isHomeActive &&
              "bg-accent/[0.10] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-4 before:rounded-full before:bg-accent",
          )}
        >
          <SpindrelLogo size={22} />
        </Link>

        <button
          onClick={toggleSidebar}
          title={`${collapsed ? "Show" : "Hide"} channel list (${modKey}+\\)`}
          aria-label={collapsed ? "Show channel list" : "Hide channel list"}
          className="sidebar-rail-btn bg-transparent border-none p-0 text-text-dim hover:text-text transition-colors"
        >
          <PanelToggleIcon size={17} />
        </button>

        <div className="h-px w-6 bg-surface-border/60 my-1" />

        <RailButton
          active={unreadInboxOpen}
          title="Inbox"
          onClick={onToggleUnreadInbox ?? (() => {})}
          badge={
            inboxTotal > 0 ? (
              <span className="absolute top-0.5 right-0.5 min-w-[15px] h-[15px] px-1 rounded-full bg-accent text-[9px] font-bold text-white flex flex-row items-center justify-center tabular-nums">
                {inboxTotal > 9 ? "9+" : inboxTotal}
              </span>
            ) : null
          }
        >
          <Inbox size={18} className={unreadInboxOpen ? "text-accent" : "text-text-dim"} />
        </RailButton>

        {isAdmin && (
          <RailLink
            href="/admin/automations?view=list"
            active={isTasksActive}
            title="Automations"
            badge={
              upcomingCount > 0 && !isTasksActive ? (
                <span className="absolute top-0.5 right-0.5 min-w-[15px] h-[15px] px-1 rounded-full bg-accent text-[9px] font-bold text-white flex flex-row items-center justify-center tabular-nums">
                  {upcomingCount > 9 ? "9+" : upcomingCount}
                </span>
              ) : null
            }
          >
            <Clock size={18} className={isTasksActive ? "text-accent" : "text-text-dim"} />
          </RailLink>
        )}

        {railDashboards.map((d) => {
          const isChannel = isChannelSlug(d.slug);
          const channelId = isChannel ? channelIdFromSlug(d.slug) : null;
          const href = channelId
            ? `/widgets/channel/${channelId}`
            : `/widgets/${d.slug}`;
          // Channel dashboards live at two path shapes (pretty + raw-slug).
          // Match both so the rail highlights correctly regardless of which
          // entry point the user followed.
          const active = channelId
            ? pathname === href
              || pathname === `/widgets/${encodeURIComponent(d.slug)}`
              || pathname === `/widgets/${d.slug}`
            : pathname === `/widgets/${d.slug}`;
          const label = channelId
            ? `#${channelNameById.get(channelId) ?? d.name}`
            : d.name;
          return (
            <RailLink key={d.slug} href={href} active={active} title={label} pinned>
              {isChannel && !d.icon ? (
                <Hash size={18} className={active ? "text-accent" : "text-text-dim"} />
              ) : (
                <LucideIconByName
                  name={d.icon}
                  size={18}
                  className={active ? "text-accent" : "text-text-dim"}
                />
              )}
            </RailLink>
          );
        })}

        {/* Separator between user content (Tasks / Widgets / pinned dashboards)
            and admin nav. Only renders when admin section is present; divider
            above pinned cluster already exists above Tasks. */}
        {isAdmin && railDashboards.length > 0 && (
          <div className="h-px w-6 bg-surface-border/60 my-1" />
        )}

        {isAdmin && (
          <>
            <RailLink href="/admin/bots" active={isBotsActive} title="Bots">
              <Bot size={18} className={isBotsActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/skills" active={isSkillsActive} title="Skills">
              <BookOpen size={18} className={isSkillsActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/projects" active={isProjectsActive} title="Projects">
              <FolderKanban size={18} className={isProjectsActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/integrations" active={isIntegrationsActive} title="Integrations">
              <Plug size={18} className={isIntegrationsActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/machines" active={isMachinesActive} title="Machines">
              <Monitor size={18} className={isMachinesActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/usage" active={isUsageActive} title="Activity">
              <BarChart3 size={18} className={isUsageActive ? "text-accent" : "text-text-dim"} />
            </RailLink>

            <RailLink href="/admin/learning" active={isLearningActive} title="Learning">
              <Brain size={18} className={isLearningActive ? "text-accent" : "text-text-dim"} />
            </RailLink>
          </>
        )}
      </div>

      <div className="flex-1" />

      {/* Bottom cluster — chrome: theme + avatar */}
      <div className="flex flex-col items-center gap-1 pb-3">
        <button
          onClick={toggleTheme}
          title={themeMode === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          aria-label={themeMode === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className="sidebar-rail-btn bg-transparent border-none p-0"
        >
          {themeMode === "dark" ? (
            <Sun size={16} className="text-text-dim" />
          ) : (
            <Moon size={16} className="text-text-dim" />
          )}
        </button>

        <button
          ref={avatarBtnRef}
          onClick={() => setAvatarOpen((v) => !v)}
          title={user?.display_name || "Account"}
          aria-label="Open account menu"
          className="sidebar-rail-btn bg-transparent border-none p-0"
        >
          <div
            className={cn(
              "w-7 h-7 rounded-md flex flex-row items-center justify-center bg-indigo-500/20",
              avatarOpen && "ring-2 ring-accent/60",
            )}
          >
            <span className="text-[11px] font-bold text-indigo-500">
              {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
            </span>
          </div>
        </button>
      </div>

      <AvatarMenu
        anchorRef={avatarBtnRef}
        open={avatarOpen}
        onClose={() => setAvatarOpen(false)}
        version={version}
      />
    </div>
  );
}
