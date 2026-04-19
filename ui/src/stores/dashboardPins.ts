import { create } from "zustand";
import type {
  GridLayoutItem,
  WidgetDashboardPin,
  ToolResultEnvelope,
} from "../types/api";
import { envelopeIdentityKey } from "./pinnedWidgets";
import { apiFetch } from "../api/client";

interface LayoutUpdateItem extends GridLayoutItem {
  id: string;
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
        const { x, y, w, h } = update;
        return { ...p, grid_layout: { x, y, w, h } };
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
