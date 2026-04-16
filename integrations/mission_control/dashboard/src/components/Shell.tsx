/**
 * App shell — sidebar + main content area + mobile bottom nav.
 *
 * - Standalone (not embedded): sidebar on desktop (md+), bottom tab bar on mobile.
 * - Embedded (iframe): bottom tab bar on mobile, no chrome on desktop.
 */

import { useState, useMemo } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  BookOpen,
  Clock,
  Brain,
  ListChecks,
  Settings,
  Wrench,
  LayoutGrid,
  MoreHorizontal,
  X,
  ArrowLeft,
} from "lucide-react";
import { useOverview } from "../hooks/useOverview";
import { isEmbedded } from "../lib/auth-bridge";

/** Tell the parent app to close this integration view */
function closeToParent() {
  try {
    window.parent.postMessage({ type: "spindrel:close" }, "*");
  } catch {
    // not embedded, ignore
  }
}
import { channelColor } from "../lib/colors";
import type { ChannelSummary } from "../lib/types";
import type { LucideIcon } from "lucide-react";

interface NavItem {
  label: string;
  to: string;
  Icon: LucideIcon;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/", Icon: LayoutDashboard },
  { label: "Kanban", to: "/kanban", Icon: LayoutGrid },
  { label: "Journal", to: "/journal", Icon: BookOpen },
  { label: "Timeline", to: "/timeline", Icon: Clock },
  { label: "Memory", to: "/memory", Icon: Brain },
  { label: "Plans", to: "/plans", Icon: ListChecks },
  { label: "Settings", to: "/settings", Icon: Settings },
  { label: "Setup", to: "/setup", Icon: Wrench },
];

// Primary tabs shown in the bottom bar; the rest go into "More"
const BOTTOM_TAB_ITEMS: NavItem[] = [
  NAV_ITEMS[0], // Overview
  NAV_ITEMS[1], // Kanban
  NAV_ITEMS[5], // Plans
  NAV_ITEMS[4], // Memory
];
const MORE_ITEMS: NavItem[] = [
  NAV_ITEMS[2], // Journal
  NAV_ITEMS[3], // Timeline
  NAV_ITEMS[6], // Settings
  NAV_ITEMS[7], // Setup
];

// ---------------------------------------------------------------------------
// Sidebar link (desktop)
// ---------------------------------------------------------------------------

function SidebarLink({ item }: { item: NavItem }) {
  const { Icon } = item;
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
          isActive
            ? "bg-accent/15 text-accent-hover"
            : "text-content-muted hover:text-content hover:bg-surface-3"
        }`
      }
    >
      <Icon size={16} className="flex-shrink-0" />
      {item.label}
    </NavLink>
  );
}

// ---------------------------------------------------------------------------
// Mobile bottom tab bar
// ---------------------------------------------------------------------------

function MobileBottomNav() {
  const [moreOpen, setMoreOpen] = useState(false);
  const location = useLocation();

  // Check if current path matches a "More" item
  const isMoreActive = MORE_ITEMS.some((item) =>
    item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to),
  );

  return (
    <>
      {/* More menu overlay */}
      {moreOpen && (
        <div className="fixed inset-0 z-40" onClick={() => setMoreOpen(false)}>
          <div
            className="absolute bottom-14 left-0 right-0 bg-surface-1 border-t border-surface-3 px-2 py-2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="grid grid-cols-4 gap-1">
              {MORE_ITEMS.map((item) => {
                const Icon = item.Icon;
                const isActive = item.to === "/"
                  ? location.pathname === "/"
                  : location.pathname.startsWith(item.to);
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={() => setMoreOpen(false)}
                    className={`flex flex-col items-center gap-1 py-2.5 rounded-lg transition-colors ${
                      isActive ? "text-accent-hover bg-accent/10" : "text-content-muted"
                    }`}
                  >
                    <Icon size={18} />
                    <span className="text-[10px]">{item.label}</span>
                  </NavLink>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Bottom bar */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-surface-1 border-t border-surface-3 safe-area-bottom">
        <div className="flex items-center justify-around px-1 py-1">
          {/* Back to app button (embedded only) */}
          {isEmbedded() && (
            <button
              onClick={closeToParent}
              className="flex flex-col items-center gap-0.5 py-1.5 px-2 rounded-lg transition-colors min-w-0 text-content-dim"
            >
              <ArrowLeft size={20} />
              <span className="text-[10px] leading-tight">Back</span>
            </button>
          )}
          {BOTTOM_TAB_ITEMS.map((item) => {
            const Icon = item.Icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={() => setMoreOpen(false)}
                className={({ isActive }) =>
                  `flex flex-col items-center gap-0.5 py-1.5 px-2 rounded-lg transition-colors min-w-0 ${
                    isActive ? "text-accent-hover" : "text-content-dim"
                  }`
                }
              >
                <Icon size={20} />
                <span className="text-[10px] leading-tight">{item.label}</span>
              </NavLink>
            );
          })}
          <button
            onClick={() => setMoreOpen(!moreOpen)}
            className={`flex flex-col items-center gap-0.5 py-1.5 px-2 rounded-lg transition-colors min-w-0 ${
              moreOpen || isMoreActive ? "text-accent-hover" : "text-content-dim"
            }`}
          >
            {moreOpen ? <X size={20} /> : <MoreHorizontal size={20} />}
            <span className="text-[10px] leading-tight">More</span>
          </button>
        </div>
      </nav>
    </>
  );
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

export default function Shell() {
  const embedded = isEmbedded();

  if (embedded) {
    return (
      <div className="h-screen flex flex-col">
        <div className="flex-1 overflow-y-auto pb-14 md:pb-0 flex flex-col">
          <div className="flex-1">
            <Outlet />
          </div>
        </div>
        <MobileBottomNav />
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      {/* Desktop sidebar — hidden on mobile */}
      <aside className="hidden md:flex w-56 flex-shrink-0 bg-surface-1 border-r border-surface-3 flex-col">
        <div className="p-4 border-b border-surface-3">
          <h1 className="text-lg font-semibold text-content">Mission Control</h1>
          <p className="text-xs text-content-dim mt-0.5">Agent Dashboard</p>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}

          <div className="mt-4 pt-3 border-t border-surface-3">
            <p className="px-3 text-xs font-medium text-content-dim uppercase tracking-wider mb-2">
              Channels
            </p>
            <ChannelNavList />
          </div>
        </nav>

        <div className="p-3 border-t border-surface-3">
          <p className="text-xs text-content-dim text-center">v0.2.0</p>
        </div>
      </aside>

      {/* Main content — bottom padding on mobile for tab bar */}
      <main className="flex-1 overflow-y-auto pb-14 md:pb-0 flex flex-col">
        <div className="flex-1">
          <Outlet />
        </div>
      </main>

      {/* Mobile bottom nav — visible on small screens */}
      <MobileBottomNav />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel nav list (desktop sidebar only)
// ---------------------------------------------------------------------------

const INITIAL_SHOW = 10;

function ChannelNavList() {
  const { data } = useOverview();
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);

  const allChannels = useMemo(() => {
    if (!data?.channels?.length) return [];
    return data.channels.filter((ch: ChannelSummary) => ch.workspace_enabled);
  }, [data]);

  if (allChannels.length === 0) {
    return <p className="px-3 text-xs text-content-dim">No workspace channels yet.</p>;
  }

  const filtered = search
    ? allChannels.filter((ch: ChannelSummary) => {
        const label = (ch.name || ch.id).toLowerCase();
        return label.includes(search.toLowerCase());
      })
    : allChannels;

  const visible = showAll ? filtered : filtered.slice(0, INITIAL_SHOW);
  const hasMore = filtered.length > INITIAL_SHOW && !showAll;

  return (
    <div className="space-y-1">
      {allChannels.length > 5 && (
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setShowAll(false); }}
          placeholder="Search..."
          className="w-full bg-surface-0 border border-surface-4 rounded px-2.5 py-1 text-xs text-content-muted placeholder-content-dim focus:outline-none focus:border-accent/40 mb-1"
        />
      )}

      <div className="space-y-0.5">
        {visible.map((ch: ChannelSummary) => (
          <NavLink
            key={ch.id}
            to={`/channels/${ch.id}`}
            title={ch.name || ch.id}
            className={({ isActive }) =>
              `flex items-center gap-2 px-3 py-1.5 rounded text-sm truncate transition-colors ${
                isActive
                  ? "bg-accent/15 text-accent-hover"
                  : "text-content-muted hover:text-content hover:bg-surface-3"
              }`
            }
          >
            <span
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: channelColor(ch.id) }}
            />
            {ch.name || ch.id.slice(0, 8)}
          </NavLink>
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full text-left px-3 py-1 text-xs text-content-dim hover:text-content-muted transition-colors"
        >
          Show all {filtered.length} channels
        </button>
      )}

      {search && filtered.length === 0 && (
        <p className="px-3 text-xs text-content-dim">No matches</p>
      )}
    </div>
  );
}
