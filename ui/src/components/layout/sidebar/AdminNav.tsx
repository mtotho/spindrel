import { useState, useEffect } from "react";
import { View, Text, Pressable } from "react-native";
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
      { label: "Carapaces (Expertise)", href: "/admin/carapaces", icon: Layers },
      { label: "Tools", href: "/admin/tools", icon: Wrench },
      { label: "Skills", href: "/admin/skills", icon: BookOpen },
      { label: "Templates", href: "/admin/prompt-templates", icon: FileText },
      { label: "Attachments", href: "/admin/attachments", icon: Paperclip },
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
      { label: "API Keys", href: "/admin/api-keys", icon: Key },
      { label: "Secrets", href: "/admin/secret-values", icon: Lock },
      { label: "Policies", href: "/admin/tool-policies", icon: Shield },
      { label: "Approvals", href: "/admin/approvals", icon: ShieldCheck },
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
      { label: "API Docs", href: "/admin/api-docs", icon: FileCode },
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

export function RailIcon({ item, active }: { item: NavItem; active: boolean }) {
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
    // Default: sections without defaultOpen start collapsed (unless they have the active page)
    const initial: Record<string, boolean> = {};
    for (const section of ADMIN_SECTIONS) {
      if (saved[section.title] !== undefined) {
        // Respect saved preference, but always expand if active page is in section
        initial[section.title] = sectionHasActive(section, pathname) ? false : saved[section.title];
      } else {
        // First load: defaultOpen sections start expanded, others collapsed unless active
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
    <>
      {ADMIN_SECTIONS.map((section) => {
        const isCollapsed = collapsed[section.title] ?? false;
        const hasActive = sectionHasActive(section, pathname);
        return (
          <View key={section.title} className="px-2 py-1.5">
            <Pressable
              onPress={() => toggle(section.title)}
              className="flex-row items-center px-3 py-1.5 rounded hover:bg-surface-overlay"
              style={{ gap: 4 }}
            >
              <ChevronRight
                size={10}
                color={hasActive ? t.accent : t.textDim}
                style={{
                  transform: [{ rotate: isCollapsed ? "0deg" : "90deg" }],
                  transition: "transform 0.15s",
                } as any}
              />
              <Text
                className={`${mobile ? "text-xs" : "text-[11px]"} font-semibold tracking-wider`}
                style={{ flex: 1, color: hasActive ? t.accent : t.textDim }}
              >
                {section.title}
              </Text>
              {isCollapsed && hasActive && (
                <View style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: t.accent }} />
              )}
            </Pressable>
            {!isCollapsed &&
              section.items.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  active={pathname.startsWith(item.href)}
                  mobile={mobile}
                />
              ))}
          </View>
        );
      })}
    </>
  );
}
