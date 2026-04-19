import { Link, useLocation } from "react-router-dom";
import {
  Clock,
  BarChart3,
  Brain,
  Bot,
  BookOpen,
  LayoutDashboard,
  Plug,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
  Moon,
} from "lucide-react";
import { useRef, useState } from "react";
import { SpindrelLogo } from "../SpindrelLogo";
import { useUIStore } from "../../../stores/ui";
import { useAuthStore } from "../../../stores/auth";
import { useThemeStore } from "../../../stores/theme";
import { useVersion } from "../../../api/hooks/useVersion";
import { useDashboards } from "../../../stores/dashboards";
import { LucideIconByName } from "../../IconPicker";
import { cn } from "../../../lib/cn";
import { useTodayUpcomingCount } from "./UpcomingRailPopover";
import { AvatarMenu } from "./AvatarMenu";

interface RailLinkProps {
  href: string;
  active?: boolean;
  title: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
}

function RailLink({ href, active, title, children, badge }: RailLinkProps) {
  return (
    <Link
      to={href}
      title={title}
      aria-label={title}
      aria-current={active ? "page" : undefined}
      className={cn(
        "sidebar-rail-btn relative bg-transparent border-none p-0",
        active &&
          "bg-accent/[0.12] before:content-[''] before:absolute before:left-0 before:top-1/2 before:-translate-y-1/2 before:w-[3px] before:h-4 before:rounded-full before:bg-accent",
      )}
    >
      {children}
      {badge}
    </Link>
  );
}

export function SidebarRail() {
  const { pathname, search } = useLocation();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const user = useAuthStore((s) => s.user);
  const themeMode = useThemeStore((s) => s.mode);
  const toggleTheme = useThemeStore((s) => s.toggle);
  const { data: version } = useVersion();
  const upcomingCount = useTodayUpcomingCount();
  const { list: dashboards } = useDashboards();
  const railDashboards = dashboards
    .filter((d) => d.pin_to_rail)
    .sort((a, b) => {
      const ap = a.rail_position ?? Number.MAX_SAFE_INTEGER;
      const bp = b.rail_position ?? Number.MAX_SAFE_INTEGER;
      if (ap !== bp) return ap - bp;
      return a.name.localeCompare(b.name);
    });

  const isTasksActive = pathname.startsWith("/admin/tasks");
  // "Widgets" rail entry lights up for /widgets (redirect) or /widgets/default;
  // pinned-dashboard entries light up for their own exact slug.
  const isWidgetsActive =
    pathname === "/widgets" ||
    pathname === "/widgets/default" ||
    pathname.startsWith("/widgets/dev");
  const isBotsActive = pathname.startsWith("/admin/bots");
  const isSkillsActive = pathname.startsWith("/admin/skills");
  const isIntegrationsActive = pathname.startsWith("/admin/integrations");
  const isUsageActive = pathname.startsWith("/admin/usage");
  const isLearningActive = pathname.startsWith("/admin/learning");
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

        <RailLink
          href="/admin/tasks?view=list"
          active={isTasksActive}
          title="Tasks"
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

        <RailLink href="/widgets" active={isWidgetsActive} title="Widgets">
          <LayoutDashboard size={18} className={isWidgetsActive ? "text-accent" : "text-text-dim"} />
        </RailLink>

        {railDashboards.map((d) => {
          const active = pathname === `/widgets/${d.slug}`;
          return (
            <RailLink
              key={d.slug}
              href={`/widgets/${d.slug}`}
              active={active}
              title={d.name}
            >
              <LucideIconByName
                name={d.icon}
                size={18}
                className={active ? "text-accent" : "text-text-dim"}
              />
            </RailLink>
          );
        })}

        <RailLink href="/admin/bots" active={isBotsActive} title="Bots">
          <Bot size={18} className={isBotsActive ? "text-accent" : "text-text-dim"} />
        </RailLink>

        <RailLink href="/admin/skills" active={isSkillsActive} title="Skills">
          <BookOpen size={18} className={isSkillsActive ? "text-accent" : "text-text-dim"} />
        </RailLink>

        <RailLink href="/admin/integrations" active={isIntegrationsActive} title="Integrations">
          <Plug size={18} className={isIntegrationsActive ? "text-accent" : "text-text-dim"} />
        </RailLink>

        <RailLink href="/admin/usage" active={isUsageActive} title="Activity">
          <BarChart3 size={18} className={isUsageActive ? "text-accent" : "text-text-dim"} />
        </RailLink>

        <RailLink href="/admin/learning" active={isLearningActive} title="Learning">
          <Brain size={18} className={isLearningActive ? "text-accent" : "text-text-dim"} />
        </RailLink>
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
