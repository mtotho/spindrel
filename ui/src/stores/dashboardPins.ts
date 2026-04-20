import { create } from "zustand";
import type {
  ChatZone,
  GridLayoutItem,
  WidgetDashboardPin,
  ToolResultEnvelope,
} from "../types/api";
import { envelopeIdentityKey } from "./pinnedWidgets";
import { apiFetch } from "../api/client";

interface LayoutUpdateItem extends GridLayoutItem {
  id: string;
  /** Set only for cross-canvas moves; omit to keep the pin's current zone. */
  zone?: ChatZone;
}

/** Matching key for a dashboard pin — `${prefix}::${identity}`. */
function dashboardEnvelopeKey(toolName: string, envelope: ToolResultEnvelope): string {
  return envelopeIdentityKey(toolName, envelope);
}

interface DashboardPinsState {
  /** Slug of the dashboard currently loaded. Drives all pin CRUD. */
  currentSlug: string;
  pins: WidgetDashboardPin[];
  /** Keyed by envelope identity — mirrors the channel store's shared-envelope
   *  map so cross-surface sync works (toggling in chat updates dashboard). */
  widgetEnvelopes: Record<string, ToolResultEnvelope>;
  hasHydrated: boolean;
  loadError: string | null;

  /** Fetch pins for the given dashboard slug. */
  hydrate: (slug?: string) => Promise<void>;

  /** Optimistic POST + server round-trip. Returns the server-created pin. */
  pinWidget: (body: {
    source_kind: "channel" | "adhoc";
    source_channel_id?: string | null;
    source_bot_id?: string | null;
    tool_name: string;
    tool_args?: Record<string, unknown>;
    widget_config?: Record<string, unknown>;
    envelope: ToolResultEnvelope;
    display_label?: string | null;
  }) => Promise<WidgetDashboardPin>;

  /** Atomically pin every member of a widget suite onto the current dashboard.
   *
   *  ``source_bot_id`` selects the iframe auth scope:
   *   - ``null`` (default) → each viewer sees data through their own account.
   *   - ``<bot id>`` → every viewer sees data through that bot's credentials.
   *  ``source_channel_id`` is required when the active dashboard is a
   *  channel dashboard (``channel:<uuid>``); the backend rejects the pin
   *  otherwise.
   */
  pinSuite: (
    suiteId: string,
    opts?: {
      members?: string[];
      source_bot_id?: string | null;
      source_channel_id?: string | null;
    },
  ) => Promise<WidgetDashboardPin[]>;

  unpinWidget: (pinId: string) => Promise<void>;

  /** Update a single pin's envelope in-place (after refresh or action response). */
  updateEnvelope: (pinId: string, envelope: ToolResultEnvelope) => void;

  /** Shallow-merge a config patch into a pin (optimistic; server persisted via dispatch). */
  patchWidgetConfig: (pinId: string, patch: Record<string, unknown>) => void;

  /**
   * Replace a pin's widget_config outright. Persists to the server with
   * merge:false. Used by the Edit Pin drawer where the intent is "what I
   * see in the JSON editor is what lives in DB after Save".
   */
  replaceWidgetConfig: (pinId: string, config: Record<string, unknown>) => Promise<void>;

  /** Rename a pin's display_label (or clear with null). */
  renamePin: (pinId: string, displayLabel: string | null) => Promise<void>;

  /**
   * Promote a pin to claim the dashboard's main area (`layout_mode = 'panel'`).
   * Server clears `is_main_panel` on every other pin in the same dashboard
   * atomically. Optimistic local write; rollback on failure.
   */
  promotePinToPanel: (pinId: string) => Promise<void>;

  /**
   * Demote the panel pin back to a normal grid tile. Server reverts the
   * dashboard's `grid_config.layout_mode` to `'grid'` if no other panel pin
   * remains. Optimistic local write; rollback on failure.
   */
  demotePinFromPanel: (pinId: string) => Promise<void>;

  /**
   * Commit a batch of {x, y, w, h} layout changes. Optimistic local write,
   * single bulk POST to the server, rollback on failure.
   */
  applyLayout: (items: LayoutUpdateItem[]) => Promise<void>;

  /** Broadcast an envelope update — stores by identity key so matching pins re-render. */
  broadcastEnvelope: (toolName: string, envelope: ToolResultEnvelope) => void;

  /** Fired by the channel-store broadcast so dashboard cards update when the
   *  same entity is toggled from a chat or OmniPanel pin. */
  onChannelBroadcast: (toolName: string, envelope: ToolResultEnvelope) => void;
}

export const useDashboardPinsStore = create<DashboardPinsState>()((set, get) => ({
  currentSlug: "default",
  pins: [],
  widgetEnvelopes: {},
  hasHydrated: false,
  loadError: null,

  hydrate: async (slug) => {
    const target = slug ?? get().currentSlug;
    // Flip currentSlug synchronously so pinWidget + any other consumer that
    // reads get().currentSlug during the fetch sees the new target. Without
    // this, clicking Pin quickly after switching the dev-panel picker routed
    // the pin to the previously-loaded dashboard.
    if (target !== get().currentSlug) {
      set({ currentSlug: target, pins: [], hasHydrated: false });
    }
    try {
      const resp = await apiFetch<{ pins: WidgetDashboardPin[] }>(
        `/api/v1/widgets/dashboard?slug=${encodeURIComponent(target)}`,
      );
      set({
        currentSlug: target,
        pins: resp.pins ?? [],
        hasHydrated: true,
        loadError: null,
      });
    } catch (err) {
      set({
        currentSlug: target,
        loadError: err instanceof Error ? err.message : String(err),
        hasHydrated: true,
      });
    }
  },

  pinWidget: async (body) => {
    const slug = get().currentSlug;
    const created = await apiFetch<WidgetDashboardPin>(
      "/api/v1/widgets/dashboard/pins",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, dashboard_key: slug }),
      },
    );
    set((s) => ({ pins: [...s.pins, created] }));
    return created;
  },

  pinSuite: async (suiteId, opts) => {
    const slug = get().currentSlug;
    const resp = await apiFetch<{ pins: WidgetDashboardPin[] }>(
      "/api/v1/widgets/dashboard/pins/suite",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          suite_id: suiteId,
          dashboard_key: slug,
          members: opts?.members,
          source_bot_id: opts?.source_bot_id ?? null,
          source_channel_id: opts?.source_channel_id ?? null,
        }),
      },
    );
    const created = resp.pins ?? [];
    set((s) => ({ pins: [...s.pins, ...created] }));
    return created;
  },

  unpinWidget: async (pinId) => {
    // Optimistic remove.
    const prev = get().pins;
    set({ pins: prev.filter((p) => p.id !== pinId) });
    try {
      await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}`, {
        method: "DELETE",
      });
    } catch (err) {
      // Rollback on failure.
      set({ pins: prev });
      throw err;
    }
  },

  updateEnvelope: (pinId, envelope) => {
    set((s) => ({
      pins: s.pins.map((p) =>
        p.id === pinId ? { ...p, envelope } : p,
      ),
    }));
  },

  patchWidgetConfig: (pinId, patch) => {
    set((s) => ({
      pins: s.pins.map((p) =>
        p.id === pinId
          ? { ...p, widget_config: { ...(p.widget_config ?? {}), ...patch } }
          : p,
      ),
    }));
  },

  replaceWidgetConfig: async (pinId, config) => {
    const prev = get().pins;
    set({
      pins: prev.map((p) =>
        p.id === pinId ? { ...p, widget_config: { ...config } } : p,
      ),
    });
    try {
      await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config, merge: false }),
      });
    } catch (err) {
      set({ pins: prev });
      throw err;
    }
  },

  promotePinToPanel: async (pinId) => {
    const prev = get().pins;
    // Optimistically clear all other panel flags + set this one. Mirrors the
    // server's atomic clear-then-set so the UI reflects the constraint
    // immediately and a single failed call rolls everything back.
    set({
      pins: prev.map((p) => ({
        ...p,
        is_main_panel: p.id === pinId,
      })),
    });
    try {
      await apiFetch(
        `/api/v1/widgets/dashboard/pins/${pinId}/promote-panel`,
        { method: "POST" },
      );
      // Server flipped grid_config.layout_mode='panel'; trigger a dashboards
      // refetch so the page render branches into panel mode without a manual
      // reload. Lazy import to avoid a store-to-store cycle at module load.
      const { useDashboardsStore } = await import("./dashboards");
      void useDashboardsStore.getState().hydrate();
    } catch (err) {
      set({ pins: prev });
      throw err;
    }
  },

  demotePinFromPanel: async (pinId) => {
    const prev = get().pins;
    set({
      pins: prev.map((p) =>
        p.id === pinId ? { ...p, is_main_panel: false } : p,
      ),
    });
    try {
      await apiFetch(
        `/api/v1/widgets/dashboard/pins/${pinId}/promote-panel`,
        { method: "DELETE" },
      );
      const { useDashboardsStore } = await import("./dashboards");
      void useDashboardsStore.getState().hydrate();
    } catch (err) {
      set({ pins: prev });
      throw err;
    }
  },

  renamePin: async (pinId, displayLabel) => {
    const prev = get().pins;
    set({
      pins: prev.map((p) =>
        p.id === pinId ? { ...p, display_label: displayLabel } : p,
      ),
    });
    try {
      await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_label: displayLabel }),
      });
    } catch (err) {
      set({ pins: prev });
      throw err;
    }
  },

  applyLayout: async (items) => {
    if (items.length === 0) return;
    const prev = get().pins;
    const byId = new Map(items.map((it) => [it.id, it]));
    // Optimistic local write.
    set({
      pins: prev.map((p) => {
        const update = byId.get(p.id);
        if (!update) return p;
        const { x, y, w, h, zone } = update;
        return {
          ...p,
          grid_layout: { x, y, w, h },
          zone: zone ?? p.zone,
        };
      }),
    });
    try {
      await apiFetch(`/api/v1/widgets/dashboard/pins/layout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items, dashboard_key: get().currentSlug }),
      });
    } catch (err) {
      set({ pins: prev });
      throw err;
    }
  },

  broadcastEnvelope: (toolName, envelope) => {
    const key = dashboardEnvelopeKey(toolName, envelope);
    set((s) => ({
      widgetEnvelopes: { ...s.widgetEnvelopes, [key]: envelope },
      pins: s.pins.map((p) => {
        if (dashboardEnvelopeKey(p.tool_name, p.envelope) !== key) return p;
        return { ...p, envelope };
      }),
    }));
  },

  onChannelBroadcast: (toolName, envelope) => {
    // Same mechanism — keyed by envelope identity. A no-op if no dashboard
    // pin matches the identity.
    get().broadcastEnvelope(toolName, envelope);
  },
}));
