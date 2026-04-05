import { useState, useEffect } from "react";
import { Link } from "expo-router";
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
  ChevronRight,
} from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useThemeTokens } from "../../../theme/tokens";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string }>;
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
  const t = useThemeTokens();
  return (
    <Link href={item.href as any} onPress={closeMobile}>
      <div
        className="sidebar-nav-item"
        style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: mobile ? "12px 12px" : "8px 12px",
          borderRadius: 6, cursor: "pointer",
          backgroundColor: active ? "rgba(59,130,246,0.15)" : undefined,
        }}
      >
        <Icon size={mobile ? 20 : 16} color={active ? t.accent : t.textDim} />
        <span style={{
          fontSize: mobile ? 15 : 14,
          color: active ? t.accent : t.textMuted,
          fontWeight: active ? 500 : 400,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {item.label}
        </span>
      </div>
    </Link>
  );
}

export function RailIcon({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const t = useThemeTokens();
  return (
    <Link href={item.href as any} onPress={closeMobile}>
      <div
        className="sidebar-icon-btn"
        title={item.label}
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

export function AdminSections({ pathname, mobile }: { pathname: string; mobile?: boolean }) {
  const t = useThemeTokens();
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
      {ADMIN_SECTIONS.map((section) => {
        const isCollapsed = collapsed[section.title] ?? false;
        const hasActive = sectionHasActive(section, pathname);
        return (
          <div key={section.title} style={{ padding: "6px 8px" }}>
            <button
              onClick={() => toggle(section.title)}
              className="sidebar-nav-item"
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "6px 12px", borderRadius: 4,
                background: "none", border: "none", cursor: "pointer",
                width: "100%", textAlign: "left",
              }}
            >
              <ChevronRight
                size={10}
                color={hasActive ? t.accent : t.textDim}
                style={{
                  transform: isCollapsed ? "rotate(0deg)" : "rotate(90deg)",
                  transition: "transform 0.15s",
                }}
              />
              <span style={{
                flex: 1,
                fontSize: mobile ? 12 : 11, fontWeight: 600,
                letterSpacing: 0.5,
                color: hasActive ? t.accent : t.textDim,
              }}>
                {section.title}
              </span>
              {isCollapsed && hasActive && (
                <span style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: t.accent, display: "inline-block" }} />
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
