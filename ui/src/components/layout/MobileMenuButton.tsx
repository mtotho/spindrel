import { Menu } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useThemeTokens } from "../../theme/tokens";

/**
 * Hamburger menu button that only renders on mobile (single column).
 * Opens the command palette — the palette IS the mobile nav surface.
 */
export function MobileMenuButton() {
  const columns = useResponsiveColumns();
  const openPalette = useUIStore((s) => s.openPalette);
  const t = useThemeTokens();

  if (columns !== "single") return null;

  return (
    <button
      className="header-icon-btn"
      onClick={openPalette}
      style={{ width: 44, height: 44 }}
      aria-label="Open navigation"
    >
      <Menu size={20} color={t.textMuted} />
    </button>
  );
}
