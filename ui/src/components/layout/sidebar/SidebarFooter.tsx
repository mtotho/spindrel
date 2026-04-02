import { View, Text, Pressable } from "react-native";
import { Link } from "expo-router";
import { Sun, Moon } from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useAuthStore } from "../../../stores/auth";
import { useThemeStore } from "../../../stores/theme";
import { useThemeTokens } from "../../../theme/tokens";
import { UsageHudBadge } from "../UsageHudBadge";

export function ThemeToggleIcon() {
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

export function SidebarFooterCollapsed({ version }: { version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const t = useThemeTokens();

  return (
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
  );
}

export function SidebarFooterExpanded({ pathname, mobile, version }: { pathname: string; mobile?: boolean; version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const t = useThemeTokens();

  return (
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
  );
}
