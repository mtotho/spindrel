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

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        onPress={closeMobile}
        className={`flex-row items-center gap-2 rounded-lg px-2.5 py-1 ${
          active ? "bg-accent text-white" : "hover:bg-surface-overlay"
        }`}
      >
        <Icon size={13} color={active ? "#ffffff" : "#9ca3af"} />
        <Text
          className={`text-xs ${active ? "text-white font-medium" : "text-text-muted"}`}
          numberOfLines={1}
        >
          {item.label}
        </Text>
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

  if (collapsed) {
    return (
      <View className="bg-surface border-r border-surface-border items-center pt-4" style={{ width: 48, flexShrink: 0 }}>
        <Pressable onPress={toggleSidebar} className="p-2">
          <ChevronRight size={16} color="#9ca3af" />
        </Pressable>
      </View>
    );
  }

  return (
    <View className="bg-surface border-r border-surface-border" style={{ width: 200, flexShrink: 0 }}>
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false}>
        {/* Header — Thoth branding */}
        <View className="flex-row items-center justify-between px-2.5 py-3">
          <Link href="/" asChild>
            <Pressable className="flex-row items-center gap-1.5">
              <Text style={{ fontSize: 16, lineHeight: 20, color: "#e5e5e5" }}>{"\u{130C5}"}</Text>
              <Text className="text-accent text-sm font-semibold tracking-wide">THOTH</Text>
            </Pressable>
          </Link>
          <Pressable onPress={toggleSidebar} className="p-1 rounded hover:bg-surface-overlay">
            <ChevronLeft size={14} color="#9ca3af" />
          </Pressable>
        </View>

        {/* Channels */}
        <View className="px-2 py-1">
          <View className="flex-row items-center justify-between px-2.5 mb-1">
            <Text className="text-text-dim text-[9px] font-semibold tracking-wider">
              CHANNELS
            </Text>
            <Link href={"/channels/new" as any} asChild>
              <Pressable onPress={closeMobile} className="p-0.5 rounded hover:bg-surface-overlay">
                <Plus size={11} color="#9ca3af" />
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
                  className={`flex-row items-center gap-2 rounded-lg px-2.5 py-1 ${
                    isActive ? "bg-accent/15" : "hover:bg-surface-overlay"
                  }`}
                >
                  <MessageSquare
                    size={12}
                    color={isActive ? "#3b82f6" : "#9ca3af"}
                  />
                  <View className="flex-1 min-w-0">
                    <Text
                      className={`text-xs ${
                        isActive ? "text-accent font-medium" : "text-text"
                      }`}
                      numberOfLines={1}
                    >
                      {displayName}
                    </Text>
                    {bot && (
                      <Text className="text-[9px] text-text-dim" numberOfLines={1}>
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
          <View key={section.title} className="px-2 py-1">
            <Text className="text-text-dim text-[9px] font-semibold tracking-wider px-2.5 mb-0.5">
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
            className={`flex-row items-center gap-2 rounded-lg px-2.5 py-1 ${
              pathname === "/profile" ? "bg-accent/15" : "hover:bg-surface-overlay"
            }`}
          >
            <View className="w-5 h-5 rounded-full bg-accent/20 items-center justify-center">
              <Text className="text-[9px] text-accent font-bold">
                {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
              </Text>
            </View>
            <Text
              className={`text-xs flex-1 ${
                pathname === "/profile" ? "text-accent font-medium" : "text-text-muted"
              }`}
              numberOfLines={1}
            >
              {user?.display_name || "Profile"}
            </Text>
          </Pressable>
        </Link>
        <Link href={"/(app)/settings" as any} asChild>
          <Pressable onPress={closeMobile} className="flex-row items-center gap-2 rounded-lg px-2.5 py-1 hover:bg-surface-overlay">
            <Settings size={13} color="#9ca3af" />
            <Text className="text-xs text-text-muted">Settings</Text>
          </Pressable>
        </Link>
      </View>
    </View>
  );
}
