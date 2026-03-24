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
  Database,
  FileText,
  ScrollText,
  GitBranch,
  HardDrive,
  ChevronLeft,
  ChevronRight,
  Settings,
} from "lucide-react";
import { useUIStore } from "../../stores/ui";
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
      { label: "Sessions", href: "/admin/sessions", icon: ScrollText },
    ],
  },
  {
    title: "KNOWLEDGE",
    items: [
      { label: "Skills", href: "/admin/skills", icon: BookOpen },
      { label: "Knowledge", href: "/admin/knowledge", icon: Brain },
      { label: "Memories", href: "/admin/memories", icon: Database },
    ],
  },
  {
    title: "AUTOMATION",
    items: [
      { label: "Tasks", href: "/admin/tasks", icon: ClipboardList },
      { label: "Delegations", href: "/admin/delegations", icon: GitBranch },
    ],
  },
  {
    title: "SYSTEM",
    items: [
      { label: "Tools", href: "/admin/tools", icon: Wrench },
      { label: "Providers", href: "/admin/providers", icon: Server },
      { label: "Sandboxes", href: "/admin/sandboxes", icon: HardDrive },
      { label: "Logs", href: "/admin/logs", icon: FileText },
    ],
  },
];

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link href={item.href as any} asChild>
      <Pressable
        className={`flex-row items-center gap-3 rounded-md px-3 py-2 ${
          active ? "bg-accent/20" : "hover:bg-surface-overlay"
        }`}
      >
        <Icon size={16} color={active ? "#3b82f6" : "#999999"} />
        <Text
          className={`text-sm ${active ? "text-accent font-medium" : "text-text-muted"}`}
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
  const { data: channels } = useChannels();
  const { data: bots } = useBots();

  const botMap = new Map(bots?.map((b) => [b.id, b]) ?? []);

  if (collapsed) {
    return (
      <View className="w-12 bg-surface border-r border-surface-border items-center pt-4">
        <Pressable onPress={toggleSidebar} className="p-2">
          <ChevronRight size={16} color="#999999" />
        </Pressable>
      </View>
    );
  }

  return (
    <View className="w-60 bg-surface border-r border-surface-border flex-1">
      <ScrollView className="flex-1" showsVerticalScrollIndicator={false}>
        {/* Header */}
        <View className="flex-row items-center justify-between px-4 py-3 border-b border-surface-border">
          <Text className="text-text font-semibold text-base">Agent</Text>
          <Pressable onPress={toggleSidebar} className="p-1">
            <ChevronLeft size={16} color="#999999" />
          </Pressable>
        </View>

        {/* Channels */}
        <View className="px-2 py-3">
          <View className="flex-row items-center justify-between px-2 mb-2">
            <Text className="text-text-dim text-xs font-semibold tracking-wider">
              CHANNELS
            </Text>
          </View>
          {channels?.map((channel) => {
            const bot = botMap.get(channel.bot_id);
            const isActive = pathname.includes(channel.id);
            return (
              <Link
                key={channel.id}
                href={`/channels/${channel.id}` as any}
                asChild
              >
                <Pressable
                  className={`flex-row items-center gap-3 rounded-md px-3 py-2 ${
                    isActive ? "bg-accent/20" : "hover:bg-surface-overlay"
                  }`}
                >
                  <MessageSquare
                    size={16}
                    color={isActive ? "#3b82f6" : "#999999"}
                  />
                  <View className="flex-1 min-w-0">
                    <Text
                      className={`text-sm truncate ${
                        isActive ? "text-accent font-medium" : "text-text"
                      }`}
                      numberOfLines={1}
                    >
                      {channel.display_name || channel.client_id}
                    </Text>
                    {bot && (
                      <Text className="text-xs text-text-dim" numberOfLines={1}>
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
          <View key={section.title} className="px-2 py-2">
            <Text className="text-text-dim text-xs font-semibold tracking-wider px-2 mb-1">
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

      {/* Settings footer */}
      <View className="border-t border-surface-border p-2">
        <Link href="/(app)/settings" asChild>
          <Pressable className="flex-row items-center gap-3 rounded-md px-3 py-2 hover:bg-surface-overlay">
            <Settings size={16} color="#999999" />
            <Text className="text-sm text-text-muted">Settings</Text>
          </Pressable>
        </Link>
      </View>
    </View>
  );
}
