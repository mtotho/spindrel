/**
 * Cross-surface runtime signalling for pinned widgets.
 *
 * All pins now live in ``widget_dashboard_pins`` — both dashboard-page pins
 * and per-channel sidebar pins (the latter under slug ``channel:<uuid>``).
 * See `useDashboardPinsStore` for CRUD.
 *
 * This store keeps only two concerns alive:
 *   1. Persisted UI preferences for the left OmniPanel (section collapse).
 *   2. Runtime-only envelope broadcast so an action performed in a chat
 *      widget lands on a pinned widget for the same entity without a DB
 *      roundtrip. The broadcast is dual-fired into the dashboard-pins
 *      store, which holds the real state.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ToolResultEnvelope } from "../types/api";

/**
 * Build a stable identity key for an envelope based on its integration prefix
 * and entity identifiers. Used by the shared envelope map so inline
 * WidgetCards, OmniPanel rail widgets, and dashboard tiles can all subscribe
 * to the same state.
 */
export function envelopeIdentityKey(toolName: string, envelope: ToolResultEnvelope): string {
  const prefix = toolName.includes("-") ? toolName.split("-")[0] : toolName;
  const entities = extractEntities(envelope.body);
  if (entities.size > 0) return `${prefix}::${[...entities].sort().join("|")}`;
  if (envelope.display_label) return `${prefix}::${envelope.display_label.toLowerCase()}`;
  if (envelope.record_id) return `${prefix}::rec:${envelope.record_id}`;
  return `${prefix}::${toolName}::${envelope.record_id ?? "anon"}`;
}

interface PinnedWidgetsState {
  /** Whether the files section in OmniPanel is collapsed (persisted). */
  filesSectionCollapsed: boolean;
  /** Whether the widgets section in OmniPanel is collapsed (persisted). */
  widgetsSectionCollapsed: boolean;
  /**
   * Shared envelope map — keyed by `channelId::identityKey`. Runtime-only.
   * Both chat WidgetCards and OmniPanel rail widgets read/write here so
   * toggling in either location propagates immediately to the other.
   */
  widgetEnvelopes: Record<string, ToolResultEnvelope>;

  toggleFilesSectionCollapsed: () => void;
  toggleWidgetsSectionCollapsed: () => void;

  /**
   * Broadcast an envelope update from any widget (inline chat, OmniPanel,
   * dashboard). Stores by `channelId::identityKey` so OmniPanel subscribers
   * re-render, AND forwards to the dashboard-pins store so any dashboard
   * tile (including the channel:<id> dashboard that drives the OmniPanel)
   * picks up the same envelope without a DB roundtrip.
   */
  broadcastEnvelope: (
    channelId: string,
    toolName: string,
    envelope: ToolResultEnvelope,
  ) => void;

  /**
   * Convenience wrapper for the "a new tool result just arrived in chat"
   * case. Identical to `broadcastEnvelope`.
   */
  crossUpdateFromToolResult: (
    channelId: string,
    toolName: string,
    envelope: ToolResultEnvelope,
  ) => void;
}

/**
 * Extract entity identifiers from a widget envelope body.
 */
function extractEntities(body: string | null): Set<string> {
  const entities = new Set<string>();
  if (!body) return entities;
  try {
    const parsed = typeof body === "string" ? JSON.parse(body) : body;
    for (const c of parsed?.components ?? []) {
      if (c.type === "properties" && Array.isArray(c.items)) {
        for (const item of c.items) {
          if (
            typeof item.label === "string" &&
            item.label.toLowerCase() === "entity" &&
            typeof item.value === "string"
          ) {
            entities.add(item.value.toLowerCase());
          }
        }
      }
    }
  } catch {
    // Not valid JSON
  }
  return entities;
}

export const usePinnedWidgetsStore = create<PinnedWidgetsState>()(
  persist(
    (set) => ({
      filesSectionCollapsed: false,
      widgetsSectionCollapsed: false,
      widgetEnvelopes: {},

      toggleFilesSectionCollapsed: () =>
        set((s) => ({ filesSectionCollapsed: !s.filesSectionCollapsed })),

      toggleWidgetsSectionCollapsed: () =>
        set((s) => ({ widgetsSectionCollapsed: !s.widgetsSectionCollapsed })),

      broadcastEnvelope: (channelId, toolName, envelope) => {
        const key = `${channelId}::${envelopeIdentityKey(toolName, envelope)}`;
        set((s) => ({
          widgetEnvelopes: { ...s.widgetEnvelopes, [key]: envelope },
        }));

        // Forward to the dashboard-pins store so pins on the current slug
        // (user dashboards AND channel dashboards) re-render against the
        // same envelope. Lazy import to avoid module cycles.
        import("./dashboardPins")
          .then((m) => m.useDashboardPinsStore.getState().onChannelBroadcast(toolName, envelope))
          .catch(() => { /* dashboard store not loaded — ignore */ });
      },

      crossUpdateFromToolResult: (channelId, toolName, envelope) => {
        // Delegate — same semantics.
        usePinnedWidgetsStore.getState().broadcastEnvelope(channelId, toolName, envelope);
      },
    }),
    {
      name: "spindrel-pinned-widgets",
      partialize: (s) => ({
        filesSectionCollapsed: s.filesSectionCollapsed,
        widgetsSectionCollapsed: s.widgetsSectionCollapsed,
      }),
    },
  ),
);
