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

export interface Dashboard {
  slug: string;
  name: string;
  icon: string | null;
  pin_to_rail: boolean;
  rail_position: number | null;
  /** Per-dashboard layout config. NULL = `standard` preset (legacy + default).
   *  Shape: `{ layout_type: "grid", preset: "standard" | "fine" }`. */
  grid_config: { layout_type?: string; preset?: string } | null;
  last_viewed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DashboardPatch {
  name?: string;
  icon?: string | null;
  pin_to_rail?: boolean;
  rail_position?: number | null;
  grid_config?: { layout_type: string; preset: string } | null;
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
    pin_to_rail?: boolean;
    grid_config?: { layout_type: string; preset: string } | null;
  }) => Promise<Dashboard>;
  update: (slug: string, patch: DashboardPatch) => Promise<Dashboard>;
  remove: (slug: string) => Promise<void>;
}

export const useDashboardsStore = create<DashboardsState>()((set, get) => ({
  list: [],
  hasHydrated: false,
  loadError: null,

  hydrate: async () => {
    try {
      const resp = await apiFetch<{ dashboards: Dashboard[] }>(
        "/api/v1/widgets/dashboards",
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
