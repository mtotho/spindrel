import { Pressable } from "react-native";
import { Menu } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";

/**
 * Hamburger menu button that only renders on mobile (single column).
 * Opens the mobile sidebar drawer defined in AppShell.
 */
export function MobileMenuButton() {
  const columns = useResponsiveColumns();
  const openMobile = useUIStore((s) => s.openMobileSidebar);

  if (columns !== "single") return null;

  return (
    <Pressable
      onPress={openMobile}
      className="items-center justify-center rounded-md hover:bg-surface-overlay"
      style={{ width: 44, height: 44 }}
    >
      <Menu size={20} color="#9ca3af" />
    </Pressable>
  );
}
