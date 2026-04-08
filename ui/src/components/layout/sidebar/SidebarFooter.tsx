import { Link } from "expo-router";
import { Sun, Moon, Search } from "lucide-react";
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
    <button
      onClick={toggle}
      className="sidebar-icon-btn"
      style={{
        width: 44, height: 44, borderRadius: 8,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "none", border: "none", cursor: "pointer", padding: 0,
      }}
      aria-label="Toggle theme"
    >
      {mode === "dark" ? <Sun size={16} color={t.textDim} /> : <Moon size={16} color={t.textDim} />}
    </button>
  );
}

function ThemeToggleRow() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  const t = useThemeTokens();
  return (
    <button
      onClick={toggle}
      className="sidebar-nav-item"
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "8px 12px", borderRadius: 6,
        background: "none", border: "none", cursor: "pointer",
        width: "100%", textAlign: "left",
      }}
    >
      {mode === "dark" ? <Sun size={16} color={t.textDim} /> : <Moon size={16} color={t.textDim} />}
      <span style={{ fontSize: 14, color: t.textMuted }}>
        {mode === "dark" ? "Light mode" : "Dark mode"}
      </span>
    </button>
  );
}

export function SidebarFooterCollapsed({ version }: { version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const t = useThemeTokens();

  return (
    <footer style={{
      borderTop: `1px solid ${t.surfaceBorder}`,
      display: "flex", flexDirection: "column", alignItems: "center",
      padding: "10px 0", gap: 4,
    }}>
      <UsageHudBadge collapsed />
      <ThemeToggleIcon />
      <Link href={"/(app)/profile" as any} onPress={closeMobile}>
        <div
          className="sidebar-icon-btn"
          style={{
            width: 44, height: 44, borderRadius: 8,
            display: "flex", alignItems: "center", justifyContent: "center",
            cursor: "pointer",
          }}
        >
          <div style={{
            width: 28, height: 28, borderRadius: 4,
            display: "flex", alignItems: "center", justifyContent: "center",
            backgroundColor: "rgba(99,102,241,0.2)",
          }}>
            <span style={{ fontSize: 11, color: "#6366f1", fontWeight: 700 }}>
              {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
            </span>
          </div>
        </div>
      </Link>
      {version && (
        <span style={{ fontSize: 9, color: t.textDim, opacity: 0.6 }}>
          v{version}
        </span>
      )}
    </footer>
  );
}

function SearchShortcutHint() {
  const t = useThemeTokens();
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  return (
    <button
      onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: !isMac, metaKey: isMac }))}
      className="sidebar-nav-item"
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "8px 12px", borderRadius: 6,
        background: "none", border: "none", cursor: "pointer",
        width: "100%", textAlign: "left",
      }}
    >
      <Search size={16} color={t.textDim} />
      <span style={{ flex: 1, fontSize: 14, color: t.textDim }}>Search</span>
      <kbd style={{
        fontSize: 10, color: t.textDim, background: t.surface,
        border: `1px solid ${t.surfaceBorder}`, borderRadius: 4,
        padding: "2px 6px", fontFamily: "inherit",
      }}>
        {isMac ? "\u2318" : "Ctrl"}+K
      </kbd>
    </button>
  );
}

export function SidebarFooterExpanded({ pathname, mobile, version }: { pathname: string; mobile?: boolean; version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const t = useThemeTokens();
  const isProfileActive = pathname === "/profile";

  return (
    <footer style={{
      borderTop: `1px solid ${t.surfaceBorder}`,
      padding: 10, display: "flex", flexDirection: "column", gap: 2,
    }}>
      <UsageHudBadge collapsed={false} />
      {!mobile && <SearchShortcutHint />}
      <ThemeToggleRow />
      <Link href={"/(app)/profile" as any} onPress={closeMobile}>
        <div
          className="sidebar-nav-item"
          style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: mobile ? "14px 12px" : "10px 12px",
            borderRadius: 6, cursor: "pointer",
            backgroundColor: isProfileActive ? "rgba(59,130,246,0.1)" : undefined,
          }}
        >
          <div style={{
            width: mobile ? 36 : 32, height: mobile ? 36 : 32, borderRadius: 4,
            display: "flex", alignItems: "center", justifyContent: "center",
            backgroundColor: "rgba(99,102,241,0.2)",
          }}>
            <span style={{ fontSize: mobile ? 14 : 12, color: "#6366f1", fontWeight: 700 }}>
              {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
            </span>
          </div>
          <span style={{
            flex: 1,
            fontSize: mobile ? 15 : 14,
            color: isProfileActive ? t.accent : t.textMuted,
            fontWeight: isProfileActive ? 500 : 400,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {user?.display_name || "Profile"}
          </span>
        </div>
      </Link>
      {version && (
        <span style={{ fontSize: 10, color: t.textDim, opacity: 0.5, textAlign: "center" }}>
          v{version}
        </span>
      )}
    </footer>
  );
}
