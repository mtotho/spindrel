import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PinnedWidget, ToolResultEnvelope } from "../types/api";
import { apiFetch } from "../api/client";

interface PinnedWidgetsState {
  /** Server-sourced pinned widgets, keyed by channelId */
  byChannel: Record<string, PinnedWidget[]>;
  /** Whether the files section in OmniPanel is collapsed (persisted to localStorage) */
  filesSectionCollapsed: boolean;

  toggleFilesSectionCollapsed: () => void;

  /** Hydrate from channel API response (source of truth) */
  hydrateFromChannel: (channelId: string, widgets: PinnedWidget[]) => void;

  /** Optimistic add + POST to server */
  pinWidget: (
    channelId: string,
    widget: Omit<PinnedWidget, "id" | "position" | "pinned_at">,
  ) => Promise<void>;

  /** Optimistic remove + DELETE from server */
  unpinWidget: (channelId: string, widgetId: string) => Promise<void>;

  /** Optimistic reorder + PATCH to server */
  reorderWidgets: (channelId: string, orderedIds: string[]) => Promise<void>;

  /** Update a single widget's envelope (after refresh or action response) */
  updateEnvelope: (
    channelId: string,
    widgetId: string,
    envelope: ToolResultEnvelope,
  ) => void;

  /**
   * Cross-update: when a new tool result arrives in chat, check if any pinned
   * widget should be updated. Matches by integration group (same prefix) and
   * entity overlap in the body content.
   */
  crossUpdateFromToolResult: (
    channelId: string,
    toolName: string,
    envelope: ToolResultEnvelope,
  ) => void;
}

function generateId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Extract entity identifiers from a widget envelope body.
 * Parses the component JSON and finds properties items with label "entity".
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
    (set, get) => ({
      byChannel: {},
      filesSectionCollapsed: false,

      toggleFilesSectionCollapsed: () =>
        set((s) => ({ filesSectionCollapsed: !s.filesSectionCollapsed })),

      hydrateFromChannel: (channelId, widgets) =>
        set((s) => ({
          byChannel: { ...s.byChannel, [channelId]: widgets },
        })),

      pinWidget: async (channelId, widget) => {
        const id = generateId();
        const existing = get().byChannel[channelId] ?? [];
        const entry: PinnedWidget = {
          ...widget,
          id,
          position: existing.length,
          pinned_at: new Date().toISOString(),
        };

        // Optimistic update
        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: [...(s.byChannel[channelId] ?? []), entry],
          },
        }));

        try {
          await apiFetch(`/api/v1/channels/${channelId}/widget-pins`, {
            method: "POST",
            body: JSON.stringify(entry),
          });
        } catch (err) {
          // Rollback on failure
          set((s) => ({
            byChannel: {
              ...s.byChannel,
              [channelId]: (s.byChannel[channelId] ?? []).filter(
                (w) => w.id !== id,
              ),
            },
          }));
          console.error("Failed to pin widget:", err);
        }
      },

      unpinWidget: async (channelId, widgetId) => {
        const prev = get().byChannel[channelId] ?? [];

        // Optimistic remove
        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).filter(
              (w) => w.id !== widgetId,
            ),
          },
        }));

        try {
          await apiFetch(
            `/api/v1/channels/${channelId}/widget-pins?id=${widgetId}`,
            { method: "DELETE" },
          );
        } catch (err) {
          // Rollback
          set((s) => ({
            byChannel: { ...s.byChannel, [channelId]: prev },
          }));
          console.error("Failed to unpin widget:", err);
        }
      },

      reorderWidgets: async (channelId, orderedIds) => {
        const prev = get().byChannel[channelId] ?? [];
        const reordered = orderedIds
          .map((id, i) => {
            const w = prev.find((w) => w.id === id);
            return w ? { ...w, position: i } : null;
          })
          .filter(Boolean) as PinnedWidget[];

        // Optimistic reorder
        set((s) => ({
          byChannel: { ...s.byChannel, [channelId]: reordered },
        }));

        try {
          await apiFetch(
            `/api/v1/channels/${channelId}/widget-pins/reorder`,
            {
              method: "PATCH",
              body: JSON.stringify({ ids: orderedIds }),
            },
          );
        } catch (err) {
          set((s) => ({
            byChannel: { ...s.byChannel, [channelId]: prev },
          }));
          console.error("Failed to reorder widgets:", err);
        }
      },

      updateEnvelope: (channelId, widgetId, envelope) =>
        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).map((w) =>
              w.id === widgetId ? { ...w, envelope } : w,
            ),
          },
        })),

      crossUpdateFromToolResult: (channelId, toolName, envelope) => {
        const widgets = get().byChannel[channelId];
        if (!widgets?.length) return;

        // Extract integration prefix: "homeassistant-HassTurnOn" → "homeassistant"
        const prefix = toolName.includes("-") ? toolName.split("-")[0] : "";

        // Extract entity identifiers from the new envelope body
        const newEntities = extractEntities(envelope.body);
        if (!newEntities.size && !prefix) return;

        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).map((w) => {
              // Same integration prefix?
              const wPrefix = w.tool_name.includes("-") ? w.tool_name.split("-")[0] : "";
              if (prefix && wPrefix !== prefix) return w;
              if (!prefix && w.tool_name !== toolName) return w;

              // Check entity overlap in bodies
              const pinnedEntities = extractEntities(w.envelope.body);
              if (pinnedEntities.size === 0 && newEntities.size === 0) {
                // No entities to compare — same tool name is enough
                return { ...w, envelope };
              }
              // At least one shared entity → update
              for (const e of newEntities) {
                if (pinnedEntities.has(e)) return { ...w, envelope };
              }
              return w;
            }),
          },
        }));
      },
    }),
    {
      name: "spindrel-pinned-widgets",
      partialize: (s) => ({ filesSectionCollapsed: s.filesSectionCollapsed }),
    },
  ),
);
