/**
 * App shell — sidebar + main content area.
 *
 * Designed for extensibility: the sidebar nav is data-driven so future
 * sub-modules (per-user homepages, per-bot dashboards, project pages)
 * can register their own nav items via the NAV_ITEMS array.
 */

import { useState, useMemo } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useOverview } from "../hooks/useOverview";
import { isEmbedded } from "../lib/auth-bridge";
import type { ChannelSummary } from "../lib/types";

interface NavItem {
  label: string;
  to: string;
  icon: string;
  /** Optional: only show if this returns true */
  show?: () => boolean;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/", icon: "◈" },
  { label: "Activity", to: "/activity", icon: "◉" },
  // Future sub-module routes:
  // { label: "My Board", to: "/users/me", icon: "◎" },
  // { label: "Projects", to: "/projects", icon: "◆" },
];

function SidebarLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
          isActive
            ? "bg-accent/15 text-accent-hover"
            : "text-gray-400 hover:text-gray-200 hover:bg-surface-3"
        }`
      }
    >
      <span className="text-base">{item.icon}</span>
      {item.label}
    </NavLink>
  );
}

export default function Shell() {
  const embedded = isEmbedded();
  const visibleItems = NAV_ITEMS.filter((item) => !item.show || item.show());

  // When embedded in the main app's iframe, hide the sidebar chrome —
  // the parent app's sidebar handles navigation.
  if (embedded) {
    return (
      <div className="h-screen overflow-y-auto">
        <Outlet />
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 bg-surface-1 border-r border-surface-3 flex flex-col">
        <div className="p-4 border-b border-surface-3">
          <h1 className="text-lg font-semibold text-gray-100">
            Mission Control
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">Agent Dashboard</p>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {visibleItems.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}

          {/* Channels section */}
          <div className="mt-4 pt-3 border-t border-surface-3">
            <p className="px-3 text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
              Channels
            </p>
            <ChannelNavList />
          </div>
        </nav>

        <div className="p-3 border-t border-surface-3">
          <p className="text-xs text-gray-600 text-center">v0.1.0</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

const INITIAL_SHOW = 10;

/** Sidebar channel list with search and "show more". */
function ChannelNavList() {
  const { data } = useOverview();
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);

  const allChannels = useMemo(() => {
    if (!data?.channels?.length) return [];
    return data.channels.filter((ch: ChannelSummary) => ch.workspace_enabled);
  }, [data]);

  if (allChannels.length === 0) {
    return (
      <p className="px-3 text-xs text-gray-600">
        No workspace channels yet.
      </p>
    );
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
      {/* Search — only show if enough channels to warrant it */}
      {allChannels.length > 5 && (
        <input
          type="text"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setShowAll(false); }}
          placeholder="Search..."
          className="w-full bg-surface-0 border border-surface-4 rounded px-2.5 py-1 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-accent/40 mb-1"
        />
      )}

      <div className="space-y-0.5">
        {visible.map((ch: ChannelSummary) => (
          <NavLink
            key={ch.id}
            to={`/channels/${ch.id}`}
            title={ch.name || ch.id}
            className={({ isActive }) =>
              `block px-3 py-1.5 rounded text-sm truncate transition-colors ${
                isActive
                  ? "bg-accent/15 text-accent-hover"
                  : "text-gray-400 hover:text-gray-200 hover:bg-surface-3"
              }`
            }
          >
            {ch.name || ch.id.slice(0, 8)}
          </NavLink>
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll(true)}
          className="w-full text-left px-3 py-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Show all {filtered.length} channels
        </button>
      )}

      {search && filtered.length === 0 && (
        <p className="px-3 text-xs text-gray-600">No matches</p>
      )}
    </div>
  );
}
