/**
 * App shell — sidebar + main content area.
 *
 * Designed for extensibility: the sidebar nav is data-driven so future
 * sub-modules (per-user homepages, per-bot dashboards, project pages)
 * can register their own nav items.
 */

import { NavLink, Outlet } from "react-router-dom";
import { useOverview } from "../hooks/useOverview";
import type { ChannelSummary } from "../lib/types";

interface NavItem {
  label: string;
  to: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Overview", to: "/", icon: "◈" },
  { label: "Activity", to: "/activity", icon: "◉" },
  // Future: dynamically injected items per-user, per-bot, per-project
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
          {NAV_ITEMS.map((item) => (
            <SidebarLink key={item.to} item={item} />
          ))}

          {/* Channels section — populated from data */}
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

/** Dynamically loaded channel list in sidebar. */
function ChannelNavList() {
  const { data } = useOverview();

  if (!data?.channels?.length) return null;

  const channels = data.channels
    .filter((ch: ChannelSummary) => ch.workspace_enabled)
    .slice(0, 15);

  if (channels.length === 0) return null;

  return (
    <div className="space-y-0.5">
      {channels.map((ch: ChannelSummary) => (
        <NavLink
          key={ch.id}
          to={`/channels/${ch.id}`}
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
  );
}
