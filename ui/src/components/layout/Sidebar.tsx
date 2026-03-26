import { View, Text, Pressable, ScrollView } from "react-native";
import { Link, usePathname } from "expo-router";
import {
  MessageSquare,
  Bot,
  Brain,
  BookOpen,
  ClipboardList,
  Wrench,
  Server,
  FileText,
  HardDrive,
  ChevronLeft,
  ChevronRight,
  Settings,
  Users,
  Container,
  Plus,
} from "lucide-react";
import { useUIStore } from "../../stores/ui";
import { useAuthStore } from "../../stores/auth";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string }>;
}

const ADMIN_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "AGENTS",
    items: [
      { label: "Bots", href: "/admin/bots", icon: Bot },
    ],
  },
  {
    title: "KNOWLEDGE",
    items: [
      { label: "Skills", href: "/admin/skills", icon: BookOpen },
      { label: "Knowledge", href: "/admin/knowledge", icon: Brain },
      { label: "Templates", href: "/admin/prompt-templates", icon: FileText },
    ],
  },
  {
    title: "AUTOMATION",
    items: [
      { label: "Tasks", href: "/admin/tasks", icon: ClipboardList },
    ],
  },
  {
    title: "SYSTEM",
    items: [
      { label: "Tools", href: "/admin/tools", icon: Wrench },
      { label: "Providers", href: "/admin/providers", icon: Server },
      { label: "Workspaces", href: "/admin/workspaces", icon: Container },
      { label: "Sandboxes", href: "/admin/sandboxes", icon: HardDrive },
      { label: "Users", href: "/admin/users", icon: Users },
      { label: "Logs", href: "/admin/logs", icon: FileText },
    ],
  },
];

const ALL_NAV_ITEMS: NavItem[] = ADMIN_SECTIONS.flatMap((s) => s.items);

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`flex-row items-center gap-2.5 rounded-lg px-2.5 py-2.5 ${
          active ? "bg-accent text-white" : "hover:bg-surface-overlay"
        }`}
      >
        <Icon size={16} color={active ? "#ffffff" : "#9ca3af"} />
        <Text
          className={`text-sm ${active ? "text-white font-medium" : "text-text-muted"}`}
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
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`items-center justify-center rounded-lg ${
          active ? "bg-accent" : "hover:bg-surface-overlay"
        }`}
        style={{ width: 44, height: 44 }}
        accessibilityLabel={item.label}
      >
        <Icon size={18} color={active ? "#ffffff" : "#9ca3af"} />
      </Pressable>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const { data: channels } = useChannels();
  const { data: bots } = useBots();

  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);

  // -----------------------------------------------------------------------
  // Collapsed: icon rail (56px)
  // -----------------------------------------------------------------------
  if (collapsed) {
    return (
      <View className="flex-1 bg-surface border-r border-surface-border items-center" style={{ width: 56, flexShrink: 0 }}>
        <ScrollView className="flex-1" showsVerticalScrollIndicator={false} contentContainerStyle={{ alignItems: "center", paddingTop: 8, paddingBottom: 8, gap: 2 }}>
          {/* Expand toggle */}
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded-lg hover:bg-surface-overlay"
            style={{ width: 44, height: 44 }}
            accessibilityLabel="Expand sidebar"
          >
            <ChevronRight size={16} color="#9ca3af" />
          </Pressable>

          {/* Channels icon */}
          <Link href="/" asChild>
            <Pressable
              onPress={closeMobile}
              className={`items-center justify-center rounded-lg ${
                pathname === "/" ? "bg-accent/15" : "hover:bg-surface-overlay"
              }`}
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Channels"
            >
              <MessageSquare size={18} color={pathname === "/" ? "#3b82f6" : "#9ca3af"} />
            </Pressable>
          </Link>

          {/* Divider */}
          <View className="bg-surface-border my-1" style={{ height: 1, width: 32 }} />

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
        <View className="border-t border-surface-border items-center py-2 gap-1">
          <Link href={"/(app)/profile" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className="items-center justify-center rounded-lg hover:bg-surface-overlay"
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Profile"
            >
              <View className="w-6 h-6 rounded-full bg-accent/20 items-center justify-center">
                <Text className="text-[10px] text-accent font-bold">
                  {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
                </Text>
              </View>
            </Pressable>
          </Link>
          <Link href={"/(app)/settings" as any} asChild>
            <Pressable
              onPress={closeMobile}
              className="items-center justify-center rounded-lg hover:bg-surface-overlay"
              style={{ width: 44, height: 44 }}
              accessibilityLabel="Settings"
            >
              <Settings size={18} color="#9ca3af" />
            </Pressable>
          </Link>
        </View>
      </View>
    );
  }

  // -----------------------------------------------------------------------
  // Expanded sidebar
  // -----------------------------------------------------------------------
  return (
    <View className="flex-1 bg-surface border-r border-surface-border" style={{ width: 220, flexShrink: 0 }}>
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false}>
        {/* Header — Thoth branding */}
        <View className="flex-row items-center justify-between px-3 py-3">
          <Link href="/" asChild>
            <Pressable className="flex-row items-center gap-1.5">
              <Text style={{ fontSize: 16, lineHeight: 20, color: "#e5e5e5" }}>{"\u{130C5}"}</Text>
              <Text className="text-accent text-sm font-semibold tracking-wide">THOTH</Text>
            </Pressable>
          </Link>
          <Pressable
            onPress={toggleSidebar}
            className="items-center justify-center rounded hover:bg-surface-overlay"
            style={{ width: 32, height: 32 }}
          >
            <ChevronLeft size={14} color="#9ca3af" />
          </Pressable>
        </View>

        {/* Channels */}
        <View className="px-2 py-1.5">
          <View className="flex-row items-center justify-between px-2.5 mb-1">
            <Text className="text-text-dim text-[10px] font-semibold tracking-wider py-1.5">
              CHANNELS
            </Text>
            <Link href={"/channels/new" as any} asChild>
              <Pressable
                onPress={closeMobile}
                className="items-center justify-center rounded hover:bg-surface-overlay"
                style={{ width: 28, height: 28 }}
              >
                <Plus size={13} color="#9ca3af" />
              </Pressable>
            </Link>
          </View>
          {channels?.map((channel) => {
            const bot = botMap.get(channel.bot_id);
            const isActive = pathname.includes(channel.id);
            const displayName = channel.display_name || channel.name || channel.client_id;
            return (
              <Link
                key={channel.id}
                href={`/channels/${channel.id}` as any}
                asChild
              >
                <Pressable
                  onPress={closeMobile}
                  className={`flex-row items-center gap-2.5 rounded-lg px-2.5 py-2 ${
                    isActive ? "bg-accent/15" : "hover:bg-surface-overlay"
                  }`}
                >
                  <MessageSquare
                    size={16}
                    color={isActive ? "#3b82f6" : "#9ca3af"}
                  />
                  <View className="flex-1 min-w-0">
                    <Text
                      className={`text-sm ${
                        isActive ? "text-accent font-medium" : "text-text"
                      }`}
                      numberOfLines={1}
                    >
                      {displayName}
                    </Text>
                    {bot && (
                      <Text className="text-[10px] text-text-dim" numberOfLines={1}>
                        {bot.name}
                      </Text>
                    )}
                  </View>
                </Pressable>
              </Link>
            );
          })}
        </View>

        {/* Admin sections */}
        {ADMIN_SECTIONS.map((section) => (
          <View key={section.title} className="px-2 py-1.5">
            <Text className="text-text-dim text-[10px] font-semibold tracking-wider px-2.5 py-1.5">
              {section.title}
            </Text>
            {section.items.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                active={pathname.startsWith(item.href)}
              />
            ))}
          </View>
        ))}
      </ScrollView>

      {/* Footer — profile + settings */}
      <View className="border-t border-surface-border p-2 gap-0.5">
        <Link href={"/(app)/profile" as any} asChild>
          <Pressable
            onPress={closeMobile}
            className={`flex-row items-center gap-2.5 rounded-lg px-2.5 py-2.5 ${
              pathname === "/profile" ? "bg-accent/15" : "hover:bg-surface-overlay"
            }`}
          >
            <View className="w-6 h-6 rounded-full bg-accent/20 items-center justify-center">
              <Text className="text-[10px] text-accent font-bold">
                {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
              </Text>
            </View>
            <Text
              className={`text-sm flex-1 ${
                pathname === "/profile" ? "text-accent font-medium" : "text-text-muted"
              }`}
              numberOfLines={1}
            >
              {user?.display_name || "Profile"}
            </Text>
          </Pressable>
        </Link>
        <Link href={"/(app)/settings" as any} asChild>
          <Pressable
            onPress={closeMobile}
            className="flex-row items-center gap-2.5 rounded-lg px-2.5 py-2.5 hover:bg-surface-overlay"
          >
            <Settings size={16} color="#9ca3af" />
            <Text className="text-sm text-text-muted">Settings</Text>
          </Pressable>
        </Link>
      </View>
    </View>
  );
}
