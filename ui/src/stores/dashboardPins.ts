import { create } from "zustand";
import type { WidgetDashboardPin, ToolResultEnvelope } from "../types/api";
import { envelopeIdentityKey } from "./pinnedWidgets";
import { apiFetch } from "../api/client";

/** Matching key for a dashboard pin — `${prefix}::${identity}`. */
function dashboardEnvelopeKey(toolName: string, envelope: ToolResultEnvelope): string {
  return envelopeIdentityKey(toolName, envelope);
}

interface DashboardPinsState {
  pins: WidgetDashboardPin[];
  /** Keyed by envelope identity — mirrors the channel store's shared-envelope
   *  map so cross-surface sync works (toggling in chat updates dashboard). */
  widgetEnvelopes: Record<string, ToolResultEnvelope>;
  hasHydrated: boolean;
  loadError: string | null;

  /** Fetch current pins from the server. */
  hydrate: () => Promise<void>;

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

  /** Broadcast an envelope update — stores by identity key so matching pins re-render. */
  broadcastEnvelope: (toolName: string, envelope: ToolResultEnvelope) => void;

  /** Fired by the channel-store broadcast so dashboard cards update when the
   *  same entity is toggled from a chat or OmniPanel pin. */
  onChannelBroadcast: (toolName: string, envelope: ToolResultEnvelope) => void;
}

export const useDashboardPinsStore = create<DashboardPinsState>()((set, get) => ({
  pins: [],
  widgetEnvelopes: {},
  hasHydrated: false,
  loadError: null,

  hydrate: async () => {
    try {
      const resp = await apiFetch<{ pins: WidgetDashboardPin[] }>(
        "/api/v1/widgets/dashboard",
      );
      set({ pins: resp.pins ?? [], hasHydrated: true, loadError: null });
    } catch (err) {
      set({ loadError: err instanceof Error ? err.message : String(err), hasHydrated: true });
    }
  },

  pinWidget: async (body) => {
    const created = await apiFetch<WidgetDashboardPin>(
      "/api/v1/widgets/dashboard/pins",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
