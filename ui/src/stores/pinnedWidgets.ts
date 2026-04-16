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
}

function generateId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
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
    }),
    {
      name: "spindrel-pinned-widgets",
      partialize: (s) => ({ filesSectionCollapsed: s.filesSectionCollapsed }),
    },
  ),
);
