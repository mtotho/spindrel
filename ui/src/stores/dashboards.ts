import { useEffect } from "react";
import { create } from "zustand";
import { apiFetch } from "../api/client";

export interface Dashboard {
  slug: string;
  name: string;
  icon: string | null;
  pin_to_rail: boolean;
  rail_position: number | null;
  last_viewed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DashboardPatch {
  name?: string;
  icon?: string | null;
  pin_to_rail?: boolean;
  rail_position?: number | null;
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

/** Hook: hydrate the dashboards list on first mount. */
export function useDashboards() {
  const list = useDashboardsStore((s) => s.list);
  const hasHydrated = useDashboardsStore((s) => s.hasHydrated);
  const loadError = useDashboardsStore((s) => s.loadError);
  const hydrate = useDashboardsStore((s) => s.hydrate);

  useEffect(() => {
    if (!hasHydrated) void hydrate();
  }, [hasHydrated, hydrate]);

  return { list, isLoading: !hasHydrated, error: loadError, refetch: hydrate };
}
