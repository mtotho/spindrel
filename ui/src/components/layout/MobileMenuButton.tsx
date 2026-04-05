import { Menu } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useThemeTokens } from "../../theme/tokens";

/**
 * Hamburger menu button that only renders on mobile (single column).
 * Opens the mobile sidebar drawer defined in AppShell.
 */
export function MobileMenuButton() {
  const columns = useResponsiveColumns();
  const openMobile = useUIStore((s) => s.openMobileSidebar);
  const t = useThemeTokens();

  if (columns !== "single") return null;

  return (
    <button
      className="header-icon-btn"
      onClick={openMobile}
      style={{ width: 44, height: 44 }}
    >
      <Menu size={20} color={t.textMuted} />
    </button>
  );
}
