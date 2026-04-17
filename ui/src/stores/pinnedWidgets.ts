import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { PinnedWidget, ToolResultEnvelope } from "../types/api";
import { apiFetch } from "../api/client";

/**
 * Build a stable identity key for an envelope based on its integration prefix
 * and entity identifiers. Used by the shared envelope map so inline WidgetCards
 * and PinnedToolWidgets can subscribe to the same state.
 */
export function envelopeIdentityKey(toolName: string, envelope: ToolResultEnvelope): string {
  const prefix = toolName.includes("-") ? toolName.split("-")[0] : toolName;
  const entities = extractEntities(envelope.body);
  if (entities.size > 0) return `${prefix}::${[...entities].sort().join("|")}`;
  // Use display_label as identity when entities aren't extractable
  if (envelope.display_label) return `${prefix}::${envelope.display_label.toLowerCase()}`;
  if (envelope.record_id) return `${prefix}::rec:${envelope.record_id}`;
  // Last resort: include full tool name to avoid cross-tool collisions
  return `${prefix}::${toolName}::${envelope.record_id ?? "anon"}`;
}

interface PinnedWidgetsState {
  /** Server-sourced pinned widgets, keyed by channelId */
  byChannel: Record<string, PinnedWidget[]>;
  /** Whether the files section in OmniPanel is collapsed (persisted to localStorage) */
  filesSectionCollapsed: boolean;
  /**
   * Shared envelope map — keyed by `channelId::identityKey`.
   * Both inline WidgetCards and PinnedToolWidgets read/write here so that
   * toggling in either location propagates immediately. Runtime-only (not persisted).
   */
  widgetEnvelopes: Record<string, ToolResultEnvelope>;

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

  /** Shallow-merge a config patch into a pinned widget's config (optimistic + persisted). */
  patchWidgetConfig: (
    channelId: string,
    widgetId: string,
    patch: Record<string, unknown>,
  ) => void;

  /**
   * Broadcast an envelope update from any widget (inline or pinned).
   * Stores in widgetEnvelopes so subscribers re-render, and updates any
   * matching pinned widget + persists to server.
   */
  broadcastEnvelope: (
    channelId: string,
    toolName: string,
    envelope: ToolResultEnvelope,
  ) => void;

  /**
   * Cross-update: when a new tool result arrives in chat, check if any pinned
   * widget should be updated. Delegates to broadcastEnvelope internally.
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

/**
 * Check if a pinned widget matches a tool name + envelope by integration prefix
 * and entity overlap.
 */
function widgetMatchesEnvelope(
  widget: PinnedWidget,
  toolName: string,
  envelope: ToolResultEnvelope,
): boolean {
  const prefix = toolName.includes("-") ? toolName.split("-")[0] : "";
  const wPrefix = widget.tool_name.includes("-") ? widget.tool_name.split("-")[0] : "";

  if (prefix && wPrefix !== prefix) return false;
  if (!prefix && widget.tool_name !== toolName) return false;

  const newEntities = extractEntities(envelope.body);
  const pinnedEntities = extractEntities(widget.envelope.body);

  // Both have entities — check overlap
  if (newEntities.size > 0 && pinnedEntities.size > 0) {
    for (const e of newEntities) {
      if (pinnedEntities.has(e)) return true;
    }
    return false;
  }

  // Neither has extractable entities — fall back to display_label comparison
  // to avoid matching unrelated widgets of the same integration
  if (pinnedEntities.size === 0 && newEntities.size === 0) {
    const wLabel = (widget.envelope?.display_label || widget.display_name || "").toLowerCase();
    const eLabel = (envelope.display_label || "").toLowerCase();
    if (wLabel && eLabel) return wLabel === eLabel;
    // Both labels empty — only match if exact same tool name
    return widget.tool_name === toolName;
  }

  return false;
}

export const usePinnedWidgetsStore = create<PinnedWidgetsState>()(
  persist(
    (set, get) => ({
      byChannel: {},
      filesSectionCollapsed: false,
      widgetEnvelopes: {},

      toggleFilesSectionCollapsed: () =>
        set((s) => ({ filesSectionCollapsed: !s.filesSectionCollapsed })),

      hydrateFromChannel: (channelId, widgets) => {
        // Populate byChannel from server
        set((s) => ({
          byChannel: { ...s.byChannel, [channelId]: widgets },
        }));
        // Replace widgetEnvelopes for this channel — evict stale keys, seed fresh ones
        const prefix = `${channelId}::`;
        const updates: Record<string, ToolResultEnvelope> = {};
        for (const w of widgets) {
          const key = `${prefix}${envelopeIdentityKey(w.tool_name, w.envelope)}`;
          updates[key] = w.envelope;
        }
        set((s) => {
          const cleaned = Object.fromEntries(
            Object.entries(s.widgetEnvelopes).filter(([k]) => !k.startsWith(prefix)),
          );
          return { widgetEnvelopes: { ...cleaned, ...updates } };
        });
      },

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

      updateEnvelope: (channelId, widgetId, envelope) => {
        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).map((w) =>
              w.id === widgetId ? { ...w, envelope } : w,
            ),
          },
        }));
        // Persist updated envelope to server
        const updated = get().byChannel[channelId]?.find((w) => w.id === widgetId);
        if (updated) {
          apiFetch(`/api/v1/channels/${channelId}/widget-pins`, {
            method: "POST",
            body: JSON.stringify(updated),
          }).catch((err) => console.error("Failed to persist envelope update:", err));
        }
      },

      patchWidgetConfig: (channelId, widgetId, patch) => {
        // Optimistic shallow-merge. The server-side refresh/action path sends
        // the patch in its own POST, so we don't PATCH separately here —
        // dispatch:"widget_config" already persists via the channels endpoint.
        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).map((w) =>
              w.id === widgetId
                ? { ...w, config: { ...(w.config ?? {}), ...patch } }
                : w,
            ),
          },
        }));
      },

      broadcastEnvelope: (channelId, toolName, envelope) => {
        // 1. Store in shared envelope map
        const key = `${channelId}::${envelopeIdentityKey(toolName, envelope)}`;
        set((s) => ({
          widgetEnvelopes: { ...s.widgetEnvelopes, [key]: envelope },
        }));

        // 2. Update any matching pinned widgets + persist to server
        const widgets = get().byChannel[channelId];
        if (!widgets?.length) return;

        const updatedIds: string[] = [];

        set((s) => ({
          byChannel: {
            ...s.byChannel,
            [channelId]: (s.byChannel[channelId] ?? []).map((w) => {
              if (widgetMatchesEnvelope(w, toolName, envelope)) {
                updatedIds.push(w.id);
                return { ...w, envelope };
              }
              return w;
            }),
          },
        }));

        // Persist all updated pinned widgets to server
        for (const id of updatedIds) {
          const updated = get().byChannel[channelId]?.find((w) => w.id === id);
          if (updated) {
            apiFetch(`/api/v1/channels/${channelId}/widget-pins`, {
              method: "POST",
              body: JSON.stringify(updated),
            }).catch((err) => console.error("Failed to persist broadcast update:", err));
          }
        }
      },

      crossUpdateFromToolResult: (channelId, toolName, envelope) => {
        // Delegate to broadcastEnvelope — same logic, just called from message arrival
        get().broadcastEnvelope(channelId, toolName, envelope);
      },
    }),
    {
      name: "spindrel-pinned-widgets",
      partialize: (s) => ({ filesSectionCollapsed: s.filesSectionCollapsed }),
    },
  ),
);
