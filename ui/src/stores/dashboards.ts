import { useEffect, useMemo } from "react";
import { create } from "zustand";
import { apiFetch } from "../api/client";

/** Reserved prefix for per-channel implicit dashboards. Mirrors
 *  ``CHANNEL_SLUG_PREFIX`` on the backend — kept in one place to avoid
 *  drift between string comparisons across the frontend. */
export const CHANNEL_SLUG_PREFIX = "channel:";

/** Build the dashboard slug for a given channel UUID. */
export function channelSlug(channelId: string): string {
  return `${CHANNEL_SLUG_PREFIX}${channelId}`;
}

/** True when a slug names an implicit channel dashboard. */
export function isChannelSlug(slug: string | undefined | null): boolean {
  return typeof slug === "string" && slug.startsWith(CHANNEL_SLUG_PREFIX);
}

/** Extract the channel id from a channel dashboard slug, or null. */
export function channelIdFromSlug(slug: string | undefined | null): string | null {
  if (!isChannelSlug(slug)) return null;
  return (slug as string).slice(CHANNEL_SLUG_PREFIX.length) || null;
}

/** Resolved rail-pinning state for the current viewer.
 *
 *  ``me_pinned`` — a personal ``dashboard_rail_pins`` row exists for the
 *  current user. ``everyone_pinned`` — a NULL-user "for everyone" row
 *  exists (admin-set). ``effective_position`` is the personal position
 *  when pinned for me, else the everyone position, else null. */
export interface DashboardRail {
  me_pinned: boolean;
  everyone_pinned: boolean;
  effective_position: number | null;
}

export type RailScope = "everyone" | "me";

export interface Dashboard {
  slug: string;
  name: string;
  icon: string | null;
  rail: DashboardRail;
  /** Per-dashboard layout config. NULL = `standard` preset + `grid` mode.
   *  Shape: `{ layout_type, preset, layout_mode }`. `layout_mode` is `"grid"`
   *  by default (RGL canvas) or `"panel"` when one pin claims the main area
   *  and the rest surface in the rail strip. */
  grid_config: {
    layout_type?: string;
    preset?: string;
    layout_mode?: "grid" | "panel";
    borderless?: boolean;
    hover_scrollbars?: boolean;
  } | null;
  last_viewed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DashboardPatch {
  name?: string;
  icon?: string | null;
  grid_config?: {
    layout_type: string;
    preset: string;
    borderless?: boolean;
    hover_scrollbars?: boolean;
  } | null;
}

interface DashboardsState {
  list: Dashboard[];
  hasHydrated: boolean;
  loadError: string | null;

  hydrate: () => Promise<void>;
  create: (body: {
    slug: string;
    name: string;
    icon?: string | null;
    grid_config?: { layout_type: string; preset: string } | null;
  }) => Promise<Dashboard>;
  update: (slug: string, patch: DashboardPatch) => Promise<Dashboard>;
  remove: (slug: string) => Promise<void>;
  setRailPin: (
    slug: string, scope: RailScope, railPosition?: number | null,
  ) => Promise<DashboardRail>;
  unsetRailPin: (slug: string, scope: RailScope) => Promise<DashboardRail>;
}

export const useDashboardsStore = create<DashboardsState>()((set, get) => ({
  list: [],
  hasHydrated: false,
  loadError: null,

  hydrate: async () => {
    try {
      // Fetch all scopes — channel dashboards are needed by the widget dev
      // panel picker so users can target a specific channel board without
      // navigating to that dashboard first. Tab-bar consumers still use the
      // filtered ``list`` slice.
      const resp = await apiFetch<{ dashboards: Dashboard[] }>(
        "/api/v1/widgets/dashboards?scope=all",
      );
      set({ list: resp.dashboards ?? [], hasHydrated: true, loadError: null });
    } catch (err) {
      set({
        loadError: err instanceof Error ? err.message : String(err),
        hasHydrated: true,
      });
    }
  },

  create: async (body) => {
    const created = await apiFetch<Dashboard>("/api/v1/widgets/dashboards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    set((s) => ({ list: [...s.list, created] }));
    return created;
  },

  update: async (slug, patch) => {
    const updated = await apiFetch<Dashboard>(
      `/api/v1/widgets/dashboards/${encodeURIComponent(slug)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      },
    );
    set((s) => ({
      list: s.list.map((d) => (d.slug === slug ? updated : d)),
    }));
    return updated;
  },

  remove: async (slug) => {
    const prev = get().list;
    set({ list: prev.filter((d) => d.slug !== slug) });
    try {
      await apiFetch(`/api/v1/widgets/dashboards/${encodeURIComponent(slug)}`, {
        method: "DELETE",
      });
    } catch (err) {
      set({ list: prev });
      throw err;
    }
  },

  setRailPin: async (slug, scope, railPosition) => {
    const body: { scope: RailScope; rail_position?: number | null } = { scope };
    if (railPosition !== undefined) body.rail_position = railPosition;
    const resp = await apiFetch<{ slug: string; rail: DashboardRail }>(
      `/api/v1/widgets/dashboards/${encodeURIComponent(slug)}/rail`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    set((s) => ({
      list: s.list.map((d) => (d.slug === slug ? { ...d, rail: resp.rail } : d)),
    }));
    return resp.rail;
  },

  unsetRailPin: async (slug, scope) => {
    const resp = await apiFetch<{ slug: string; rail: DashboardRail }>(
      `/api/v1/widgets/dashboards/${encodeURIComponent(slug)}/rail?scope=${scope}`,
      { method: "DELETE" },
    );
    set((s) => ({
      list: s.list.map((d) => (d.slug === slug ? { ...d, rail: resp.rail } : d)),
    }));
    return resp.rail;
  },
}));

/** Hook: hydrate the dashboards list on first mount.
 *
 *  ``list`` returns only *user* dashboards (channel:<uuid> slugs filtered
 *  out) so existing tab-bar consumers stay clean. Use ``allDashboards`` or
 *  ``channelDashboards`` when you need the other slices. */
export function useDashboards() {
  const list = useDashboardsStore((s) => s.list);
  const hasHydrated = useDashboardsStore((s) => s.hasHydrated);
  const loadError = useDashboardsStore((s) => s.loadError);
  const hydrate = useDashboardsStore((s) => s.hydrate);

  useEffect(() => {
    if (!hasHydrated) void hydrate();
  }, [hasHydrated, hydrate]);

  const userList = useMemo(() => list.filter((d) => !isChannelSlug(d.slug)), [list]);

  return {
    list: userList,
    allDashboards: list,
    channelDashboards: useMemo(() => list.filter((d) => isChannelSlug(d.slug)), [list]),
    isLoading: !hasHydrated,
    error: loadError,
    refetch: hydrate,
  };
}
