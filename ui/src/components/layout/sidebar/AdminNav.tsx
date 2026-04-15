import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Bot,
  BookOpen,
  ClipboardList,
  FileText,
  ScrollText,
  Settings,
  Users,
  Key,
  Lock,
  Shield,
  ShieldCheck,
  Activity,
  HardDrive,
  Code2,
  Server,
  Plug,
  Paperclip,
  BarChart3,
  Layers,
  Zap,
  Wrench,
  Cable,
  FileCode,
  Webhook,
  Boxes,
  Brain,
  ChevronRight,
} from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { usePendingApprovalCount } from "../../../api/hooks/useApprovals";
import { cn } from "../../../lib/cn";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  badge?: React.ReactNode;
}

interface SectionDef {
  title: string;
  items: NavItem[];
  /** If true, section starts expanded even if no item is active. */
  defaultOpen?: boolean;
}

export const ADMIN_SECTIONS: SectionDef[] = [
  {
    title: "CONFIGURE",
    defaultOpen: true,
    items: [
      { label: "Bots", href: "/admin/bots", icon: Bot },
      { label: "Integrations", href: "/admin/integrations", icon: Plug },
      { label: "Providers", href: "/admin/providers", icon: Server },
      { label: "MCP Servers", href: "/admin/mcp-servers", icon: Cable },
      { label: "Capabilities", href: "/admin/carapaces", icon: Layers },
      { label: "Tools", href: "/admin/tools", icon: Wrench },
      { label: "Skills", href: "/admin/skills", icon: BookOpen },
      { label: "Templates", href: "/admin/prompt-templates", icon: FileText },
      { label: "Attachments", href: "/admin/attachments", icon: Paperclip },
      { label: "Docker Stacks", href: "/admin/docker-stacks", icon: Boxes },
    ],
  },
  {
    title: "AUTOMATE",
    items: [
      { label: "Learning", href: "/admin/learning", icon: Brain },
      { label: "Tasks", href: "/admin/tasks", icon: ClipboardList },
      { label: "Workflows", href: "/admin/workflows", icon: Zap },
    ],
  },
  {
    title: "SECURITY",
    items: [
      { label: "Secrets", href: "/admin/secret-values", icon: Lock },
      { label: "Policies", href: "/admin/tool-policies", icon: Shield },
      { label: "Approvals", href: "/admin/approvals", icon: ShieldCheck },
    ],
  },
  {
    title: "DEVELOPER",
    items: [
      { label: "API Keys", href: "/admin/api-keys", icon: Key },
      { label: "Webhooks", href: "/admin/webhooks", icon: Webhook },
      { label: "API Docs", href: "/admin/api-docs", icon: FileCode },
    ],
  },
  {
    title: "MONITOR",
    items: [
      { label: "Usage", href: "/admin/usage", icon: BarChart3 },
      { label: "Tool Calls", href: "/admin/tool-calls", icon: Activity },
      { label: "Users", href: "/admin/users", icon: Users },
      { label: "Logs", href: "/admin/logs", icon: ScrollText },
      { label: "Diagnostics", href: "/admin/diagnostics", icon: HardDrive },
      { label: "Config", href: "/admin/config-state", icon: Code2 },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = ADMIN_SECTIONS.flatMap((s) => s.items);

export function NavLink({ item, active, mobile }: { item: NavItem; active: boolean; mobile?: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  return (
    <Link to={item.href} onClick={closeMobile}>
      <div
        className={cn(
          "sidebar-item",
          mobile && "py-3",
          active && "sidebar-item-active",
        )}
      >
        <span className={cn(active ? "text-accent/70" : "text-text-dim/60")}>
          <Icon size={mobile ? 18 : 14} />
        </span>
        <span
          className={cn(
            "flex-1 truncate",
            mobile ? "text-[15px]" : "text-[13px]",
            active ? "text-text font-medium" : "text-text-muted",
          )}
        >
          {item.label}
        </span>
        {item.badge}
      </div>
    </Link>
  );
}

export function RailIcon({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  return (
    <Link to={item.href} onClick={closeMobile}>
      <div
        className={cn(
          "sidebar-rail-btn relative",
          active && "bg-accent/15",
        )}
        title={item.label}
      >
        <span className={cn(active ? "text-accent" : "text-text-dim")}>
          <Icon size={18} />
        </span>
        {item.badge && (
          <span className="absolute top-1 right-1">
            {item.badge}
          </span>
        )}
      </div>
    </Link>
  );
}

/** Check if any item in a section matches the current pathname. */
function sectionHasActive(section: SectionDef, pathname: string): boolean {
  return section.items.some((item) => pathname.startsWith(item.href));
}

const STORAGE_KEY = "admin-nav-collapsed";

function loadCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveCollapsed(state: Record<string, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

function PendingBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="inline-flex flex-row items-center justify-center min-w-[18px] h-[18px] rounded-full bg-red-500 text-white text-[11px] font-semibold px-[5px] leading-none">
      {count > 99 ? "99+" : count}
    </span>
  );
}

export function AdminSections({ pathname, mobile }: { pathname: string; mobile?: boolean }) {
  const { data: pendingCount = 0 } = usePendingApprovalCount();

  // Inject badge into the Approvals nav item
  const sections = useMemo(() => {
    if (pendingCount <= 0) return ADMIN_SECTIONS;
    return ADMIN_SECTIONS.map((section) => ({
      ...section,
      items: section.items.map((item) =>
        item.href === "/admin/approvals"
          ? { ...item, badge: <PendingBadge count={pendingCount} /> }
          : item,
      ),
    }));
  }, [pendingCount]);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const saved = loadCollapsed();
    const initial: Record<string, boolean> = {};
    for (const section of ADMIN_SECTIONS) {
      if (saved[section.title] !== undefined) {
        initial[section.title] = sectionHasActive(section, pathname) ? false : saved[section.title];
      } else {
        initial[section.title] = section.defaultOpen ? false : !sectionHasActive(section, pathname);
      }
    }
    return initial;
  });

  // Auto-expand when navigating to a page in a collapsed section
  useEffect(() => {
    setCollapsed((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const section of ADMIN_SECTIONS) {
        if (next[section.title] && sectionHasActive(section, pathname)) {
          next[section.title] = false;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [pathname]);

  const toggle = (title: string) => {
    setCollapsed((prev) => {
      const next = { ...prev, [title]: !prev[title] };
      saveCollapsed(next);
      return next;
    });
  };

  return (
    <nav>
      {sections.map((section) => {
        const isCollapsed = collapsed[section.title] ?? false;
        const hasActive = sectionHasActive(section, pathname);
        return (
          <div key={section.title} className="px-3 pt-4 pb-0">
            <button
              onClick={() => toggle(section.title)}
              className="sidebar-section-label flex flex-row items-center gap-1 w-full text-left bg-transparent border-none cursor-pointer px-3"
            >
              <ChevronRight
                size={10}
                color="currentColor"
                className={cn(
                  "transition-transform duration-150",
                  hasActive ? "text-accent" : "text-text-dim",
                  !isCollapsed && "rotate-90",
                )}
              />
              <span
                className={cn(
                  "flex-1",
                  hasActive ? "text-accent" : "text-text-dim",
                )}
              >
                {section.title}
              </span>
              {isCollapsed && hasActive && (
                <span className="inline-block w-[5px] h-[5px] rounded-full bg-accent" />
              )}
            </button>
            {!isCollapsed &&
              section.items.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  active={pathname.startsWith(item.href)}
                  mobile={mobile}
                />
              ))}
          </div>
        );
      })}
    </nav>
  );
}
