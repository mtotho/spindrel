import { Link, useLocation } from "react-router-dom";
import { Search, Settings as SettingsIcon } from "lucide-react";
import { useUIStore } from "../../../stores/ui";
import { UsageHudBadge } from "../UsageHudBadge";
import { useIsAdmin } from "../../../hooks/useScope";
import { cn } from "../../../lib/cn";

function SettingsRow({ to }: { to: string }) {
  const { pathname } = useLocation();
  const closeMobile = useUIStore((s) => s.closeMobileSidebar);
  const active = pathname === to || pathname.startsWith(`${to}/`) || pathname.startsWith("/settings");
  return (
    <Link
      to={to}
      onClick={closeMobile}
      className={cn(
        "flex flex-row items-center gap-2 px-3 py-1.5 rounded-md transition-colors",
        "hover:bg-surface-overlay/60",
        active && "bg-accent/[0.08] text-text",
      )}
    >
      <SettingsIcon
        size={14}
        className={active ? "text-accent" : "text-text-dim"}
      />
      <span
        className={cn(
          "flex-1 text-[12px]",
          active ? "text-text font-medium" : "text-text-muted",
        )}
      >
        Settings
      </span>
    </Link>
  );
}

function SearchShortcutHint() {
  const openPalette = useUIStore((s) => s.openPalette);
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  return (
    <button
      onClick={openPalette}
      className="flex flex-row items-center gap-2 w-full px-3 py-1.5 rounded-md bg-transparent border-none text-left cursor-pointer hover:bg-surface-overlay/60 transition-colors"
    >
      <Search size={14} className="text-text-dim" />
      <span className="flex-1 text-[12px] text-text-dim">Search</span>
      <kbd className="text-[10px] text-text-dim bg-surface-overlay/60 border border-surface-border rounded px-1.5 py-0.5 font-[inherit]">
        {isMac ? "\u2318" : "Ctrl"}+K
      </kbd>
    </button>
  );
}

export function SidebarFooter() {
  const isAdmin = useIsAdmin();
  return (
    <footer className="px-2 pt-2 pb-3 flex flex-col gap-0.5 border-t border-surface-border/40">
      <SettingsRow to={isAdmin ? "/settings" : "/settings/account"} />
      <SearchShortcutHint />
      {isAdmin && (
        <div className="px-1 pt-1">
          <UsageHudBadge collapsed={false} />
        </div>
      )}
    </footer>
  );
}
