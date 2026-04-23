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
import { buildWidgetSyncSignature } from "../lib/widgetEnvelopeSync";
/**
 * Build a stable identity key for an envelope based on its integration prefix
 * and entity identifiers. Used by the shared envelope map so inline
 * WidgetCards, OmniPanel rail widgets, and dashboard tiles can all subscribe
 * to the same state.
 */
export function envelopeIdentityKey(toolName, envelope) {
    const prefix = toolName.includes("-") ? toolName.split("-")[0] : toolName;
    // HTML widgets loaded from a workspace file have an empty `body`; their
    // identity is the path within the channel's workspace. Without this, two
    // different emit_html_widget calls collapse to the same anon identity and
    // pinning any one of them makes all of them appear "already pinned".
    if (envelope.source_path) {
        const ch = envelope.source_channel_id ?? "";
        return `${prefix}::path:${ch}:${envelope.source_path}`;
    }
    const entities = extractEntities(envelope.body);
    if (entities.size > 0)
        return `${prefix}::${[...entities].sort().join("|")}`;
    if (envelope.display_label)
        return `${prefix}::${envelope.display_label.toLowerCase()}`;
    if (envelope.record_id)
        return `${prefix}::rec:${envelope.record_id}`;
    return `${prefix}::${toolName}::${envelope.record_id ?? "anon"}`;
}
/**
 * Extract entity identifiers from a widget envelope body.
 */
function extractEntities(body) {
    const entities = new Set();
    if (!body)
        return entities;
    try {
        const parsed = typeof body === "string" ? JSON.parse(body) : body;
        for (const c of parsed?.components ?? []) {
            if (c.type === "properties" && Array.isArray(c.items)) {
                for (const item of c.items) {
                    if (typeof item.label === "string" &&
                        item.label.toLowerCase() === "entity" &&
                        typeof item.value === "string") {
                        entities.add(item.value.toLowerCase());
                    }
                }
            }
        }
    }
    catch {
        // Not valid JSON
    }
    return entities;
}
export const usePinnedWidgetsStore = create()(persist((set) => ({
    filesSectionCollapsed: false,
    widgetsSectionCollapsed: false,
    widgetEnvelopes: {},
    toggleFilesSectionCollapsed: () => set((s) => ({ filesSectionCollapsed: !s.filesSectionCollapsed })),
    toggleWidgetsSectionCollapsed: () => set((s) => ({ widgetsSectionCollapsed: !s.widgetsSectionCollapsed })),
    broadcastEnvelope: (channelId, toolName, envelope, opts) => {
        const key = `${channelId}::${envelopeIdentityKey(toolName, envelope)}`;
        const update = {
            kind: opts?.kind ?? "tool_result",
            sourceToolName: toolName,
            sourceSignature: buildWidgetSyncSignature(toolName, opts?.widgetConfig),
            envelope,
        };
        set((s) => ({
            widgetEnvelopes: { ...s.widgetEnvelopes, [key]: update },
        }));
        // Forward to the dashboard-pins store so pins on the current slug
        // (user dashboards AND channel dashboards) re-render against the
        // same envelope. Lazy import to avoid module cycles.
        import("./dashboardPins")
            .then((m) => m.useDashboardPinsStore.getState().onChannelBroadcast(toolName, envelope, opts))
            .catch(() => { });
    },
    crossUpdateFromToolResult: (channelId, toolName, envelope, opts) => {
        // Delegate — same semantics.
        usePinnedWidgetsStore.getState().broadcastEnvelope(channelId, toolName, envelope, {
            kind: "tool_result",
            widgetConfig: opts?.widgetConfig,
        });
    },
}), {
    name: "spindrel-pinned-widgets",
    partialize: (s) => ({
        filesSectionCollapsed: s.filesSectionCollapsed,
        widgetsSectionCollapsed: s.widgetsSectionCollapsed,
    }),
}));
