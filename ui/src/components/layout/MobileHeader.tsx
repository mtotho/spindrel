import { View, Text, Pressable } from "react-native";
import { ArrowLeft, Menu } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";

interface MobileHeaderProps {
  title: string;
  subtitle?: string;
  /** If provided, shows a back arrow instead of hamburger. */
  onBack?: () => void;
  /** Right-side action slot (buttons, etc.) */
  right?: React.ReactNode;
}

/**
 * Unified page header with hamburger (list pages) or back arrow (detail pages).
 *
 * Always renders the header bar with title and optional right slot.
 * The nav button (hamburger / back) only shows when the sidebar is
 * hidden (mobile) or collapsed (desktop), unless onBack is set — then
 * the back arrow always appears.
 */
export function MobileHeader({ title, subtitle, onBack, right }: MobileHeaderProps) {
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const openMobileSidebar = useUIStore((s) => s.openMobileSidebar);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  const sidebarHidden = columns === "single" || sidebarCollapsed;

  return (
    <View
      className="flex-row items-center gap-3 px-4 py-2 border-b border-surface-border bg-surface"
      style={{ flexShrink: 0 }}
    >
      {onBack ? (
        <Pressable
          onPress={onBack}
          className="items-center justify-center rounded-md hover:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
          accessibilityLabel="Go back"
        >
          <ArrowLeft size={20} color="#9ca3af" />
        </Pressable>
      ) : sidebarHidden ? (
        <Pressable
          onPress={columns === "single" ? openMobileSidebar : toggleSidebar}
          className="items-center justify-center rounded-md hover:bg-surface-overlay"
          style={{ width: 44, height: 44 }}
          accessibilityLabel="Open menu"
        >
          <Menu size={20} color="#9ca3af" />
        </Pressable>
      ) : null}

      <View className="flex-1 min-w-0">
        <Text className="text-text font-semibold" numberOfLines={1}>
          {title}
        </Text>
        {subtitle ? (
          <Text className="text-text-muted text-xs" numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
      </View>

      {right}
    </View>
  );
}
