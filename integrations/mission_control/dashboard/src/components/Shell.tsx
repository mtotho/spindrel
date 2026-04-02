/**
 * App shell — sidebar + main content area.
 *
 * When embedded inside the main app's iframe, the sidebar is hidden
 * because the parent app's sidebar handles navigation.
 */

import { useState, useMemo } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  BookOpen,
  Clock,
  Brain,
  ListChecks,
  Settings,
  Wrench,
  LayoutGrid,
} from "lucide-react";
import { useOverview } from "../hooks/useOverview";
import { isEmbedded } from "../lib/auth-bridge";
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
            : "text-gray-400 hover:text-gray-200 hover:bg-surface-3"
        }`
      }
    >
      <Icon size={16} className="flex-shrink-0" />
      {item.label}
    </NavLink>
  );
}

export default function Shell() {
  const embedded = isEmbedded();

  if (embedded) {
    return (
      <div className="h-screen overflow-y-auto">
        <Outlet />
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <aside className="w-56 flex-shrink-0 bg-surface-1 border-r border-surface-3 flex flex-col">
        <div className="p-4 border-b border-surface-3">
          <h1 className="text-lg font-semibold text-gray-100">Mission Control</h1>
          <p className="text-xs text-gray-500 mt-0.5">Agent Dashboard</p>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}

          <div className="mt-4 pt-3 border-t border-surface-3">
            <p className="px-3 text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
              Channels
            </p>
            <ChannelNavList />
          </div>
        </nav>

        <div className="p-3 border-t border-surface-3">
          <p className="text-xs text-gray-600 text-center">v0.2.0</p>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

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
    return <p className="px-3 text-xs text-gray-600">No workspace channels yet.</p>;
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
              `flex items-center gap-2 px-3 py-1.5 rounded text-sm truncate transition-colors ${
                isActive
                  ? "bg-accent/15 text-accent-hover"
                  : "text-gray-400 hover:text-gray-200 hover:bg-surface-3"
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
