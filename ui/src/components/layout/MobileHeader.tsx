import { ArrowLeft, Menu } from "lucide-react";
import { useResponsiveColumns } from "../../hooks/useResponsiveColumns";
import { useUIStore } from "../../stores/ui";
import { useThemeTokens } from "../../theme/tokens";

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
 * hidden (mobile) or collapsed (desktop), unless onBack is set -- then
 * the back arrow always appears.
 */
export function MobileHeader({ title, subtitle, onBack, right }: MobileHeaderProps) {
  const columns = useResponsiveColumns();
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const openMobileSidebar = useUIStore((s) => s.openMobileSidebar);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const t = useThemeTokens();

  const sidebarHidden = columns === "single" || sidebarCollapsed;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingLeft: 16,
        paddingRight: 16,
        flexShrink: 0,
        minHeight: 52,
        borderBottom: `1px solid ${t.surfaceBorder}`,
        backgroundColor: t.surface,
      }}
    >
      {onBack ? (
        <button
          className="header-icon-btn"
          onClick={onBack}
          style={{ width: 44, height: 44 }}
          aria-label="Go back"
        >
          <ArrowLeft size={20} color={t.textMuted} />
        </button>
      ) : sidebarHidden ? (
        <button
          className="header-icon-btn"
          onClick={columns === "single" ? openMobileSidebar : toggleSidebar}
          style={{ width: 44, height: 44 }}
          aria-label="Open menu"
        >
          <Menu size={20} color={t.textMuted} />
        </button>
      ) : null}

      <div style={{ flex: 1, minWidth: 0, paddingTop: 8, paddingBottom: 8 }}>
        <span
          style={{
            display: "block",
            fontSize: 16,
            fontWeight: 700,
            color: t.text,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>
        {subtitle ? (
          <span
            style={{
              display: "block",
              fontSize: 12,
              color: t.textMuted,
              marginTop: 2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {subtitle}
          </span>
        ) : null}
      </div>

      {right}
    </div>
  );
}
