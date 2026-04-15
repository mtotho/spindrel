import { Link } from "react-router-dom";
import { Sun, Moon, Search } from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { useAuthStore } from "../../../stores/auth";
import { useThemeStore } from "../../../stores/theme";
import { UsageHudBadge } from "../UsageHudBadge";
import { cn } from "../../../lib/cn";

export function ThemeToggleIcon() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  return (
    <button
      onClick={toggle}
      className="sidebar-rail-btn bg-transparent border-none p-0"
      aria-label="Toggle theme"
    >
      {mode === "dark"
        ? <Sun size={16} className="text-text-dim" />
        : <Moon size={16} className="text-text-dim" />}
    </button>
  );
}

function ThemeToggleRow() {
  const mode = useThemeStore((s) => s.mode);
  const toggle = useThemeStore((s) => s.toggle);
  return (
    <button
      onClick={toggle}
      className="sidebar-item w-full bg-transparent border-none text-left"
    >
      {mode === "dark"
        ? <Sun size={16} className="text-text-dim" />
        : <Moon size={16} className="text-text-dim" />}
      <span className="text-sm text-text-muted">
        {mode === "dark" ? "Light mode" : "Dark mode"}
      </span>
    </button>
  );
}

export function SidebarFooterCollapsed({ version }: { version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);

  return (
    <footer className="flex flex-col items-center py-3 gap-1.5">
      <UsageHudBadge collapsed />
      <ThemeToggleIcon />
      <Link to="/profile" onClick={closeMobile}>
        <div className="sidebar-rail-btn">
          <div className="w-7 h-7 rounded flex flex-row items-center justify-center bg-indigo-500/20">
            <span className="text-[11px] font-bold text-indigo-500">
              {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
            </span>
          </div>
        </div>
      </Link>
      {version && (
        <span className="text-[9px] text-text-dim/30">
          v{version}
        </span>
      )}
    </footer>
  );
}

function SearchShortcutHint() {
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  return (
    <button
      onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: !isMac, metaKey: isMac }))}
      className="sidebar-item w-full bg-transparent border-none text-left"
    >
      <Search size={16} className="text-text-dim" />
      <span className="flex-1 text-sm text-text-dim">Search</span>
      <kbd className="text-[10px] text-text-dim bg-surface border border-surface-border rounded px-1.5 py-0.5 font-[inherit]">
        {isMac ? "\u2318" : "Ctrl"}+K
      </kbd>
    </button>
  );
}

export function SidebarFooterExpanded({ pathname, mobile, version }: { pathname: string; mobile?: boolean; version?: string }) {
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const user = useAuthStore((s) => s.user);
  const isProfileActive = pathname === "/profile";

  return (
    <footer className="px-3 pt-3 pb-4 flex flex-col gap-1">
      <UsageHudBadge collapsed={false} />
      {!mobile && <SearchShortcutHint />}
      <ThemeToggleRow />
      <Link to="/profile" onClick={closeMobile}>
        <div
          className={cn(
            "sidebar-item",
            mobile ? "py-3.5 px-3" : "py-2.5 px-3",
            isProfileActive && "sidebar-item-active",
          )}
        >
          <div className={cn(
            "rounded flex flex-row items-center justify-center bg-indigo-500/20",
            mobile ? "w-9 h-9" : "w-8 h-8",
          )}>
            <span className={cn(
              "font-bold text-indigo-500",
              mobile ? "text-sm" : "text-xs",
            )}>
              {user?.display_name?.charAt(0)?.toUpperCase() || "?"}
            </span>
          </div>
          <span className={cn(
            "flex-1 truncate",
            mobile ? "text-[15px]" : "text-sm",
            isProfileActive ? "text-accent font-medium" : "text-text-muted",
          )}>
            {user?.display_name || "Profile"}
          </span>
        </div>
      </Link>
      {version && (
        <span className="text-[10px] text-text-dim/30 text-center">
          v{version}
        </span>
      )}
    </footer>
  );
}
