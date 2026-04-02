import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import {
  Bot,
  BookOpen,
  ClipboardList,

  FileText,
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
  Cable,
  Database,
  FileCode,
} from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useThemeTokens } from "../../../theme/tokens";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string }>;
}

export const ADMIN_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "CONFIGURE",
    items: [
      { label: "Bots", href: "/admin/bots", icon: Bot },
      { label: "Integrations", href: "/admin/integrations", icon: Plug },
      { label: "Providers", href: "/admin/providers", icon: Server },
      { label: "MCP Servers", href: "/admin/mcp-servers", icon: Cable },
      { label: "Carapaces (Expertise)", href: "/admin/carapaces", icon: Layers },
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
      { label: "Logs", href: "/admin/logs", icon: FileText },
      { label: "Diagnostics", href: "/admin/diagnostics", icon: HardDrive },
      { label: "Operations", href: "/admin/operations", icon: Database },
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

export function AdminSections({ pathname, mobile }: { pathname: string; mobile?: boolean }) {
  return (
    <>
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
    </>
  );
}
