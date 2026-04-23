import { create } from "zustand";
import { envelopeIdentityKey } from "./pinnedWidgets";
import { apiFetch } from "../api/client";
import { buildWidgetSyncSignature } from "../lib/widgetEnvelopeSync";
/** Matching key for a dashboard pin — `${prefix}::${identity}`. */
function dashboardEnvelopeKey(toolName, envelope) {
    return envelopeIdentityKey(toolName, envelope);
}
export const useDashboardPinsStore = create()((set, get) => ({
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
            const resp = await apiFetch(`/api/v1/widgets/dashboard?slug=${encodeURIComponent(target)}`);
            set({
                currentSlug: target,
                pins: resp.pins ?? [],
                hasHydrated: true,
                loadError: null,
            });
        }
        catch (err) {
            set({
                currentSlug: target,
                loadError: err instanceof Error ? err.message : String(err),
                hasHydrated: true,
            });
        }
    },
    pinWidget: async (body) => {
        const slug = get().currentSlug;
        const created = await apiFetch("/api/v1/widgets/dashboard/pins", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...body, dashboard_key: slug }),
        });
        set((s) => ({ pins: [...s.pins, created] }));
        return created;
    },
    pinPreset: async (presetId, body) => {
        const slug = get().currentSlug;
        const created = await apiFetch(`/api/v1/widgets/presets/${encodeURIComponent(presetId)}/pin`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...body, dashboard_key: slug }),
        });
        set((s) => ({ pins: [...s.pins, created] }));
        return created;
    },
    pinSuite: async (suiteId, opts) => {
        const slug = get().currentSlug;
        const resp = await apiFetch("/api/v1/widgets/dashboard/pins/suite", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                suite_id: suiteId,
                dashboard_key: slug,
                members: opts?.members,
                source_bot_id: opts?.source_bot_id ?? null,
                source_channel_id: opts?.source_channel_id ?? null,
            }),
        });
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
        }
        catch (err) {
            // Rollback on failure.
            set({ pins: prev });
            throw err;
        }
    },
    updateEnvelope: (pinId, envelope) => {
        set((s) => ({
            pins: s.pins.map((p) => p.id === pinId ? { ...p, envelope } : p),
        }));
    },
    patchWidgetConfig: (pinId, patch) => {
        set((s) => ({
            pins: s.pins.map((p) => p.id === pinId
                ? { ...p, widget_config: { ...(p.widget_config ?? {}), ...patch } }
                : p),
        }));
    },
    replaceWidgetConfig: async (pinId, config) => {
        const prev = get().pins;
        set({
            pins: prev.map((p) => p.id === pinId ? { ...p, widget_config: { ...config } } : p),
        });
        try {
            await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}/config`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ config, merge: false }),
            });
        }
        catch (err) {
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
            await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}/promote-panel`, { method: "POST" });
            // Server flipped grid_config.layout_mode='panel'; trigger a dashboards
            // refetch so the page render branches into panel mode without a manual
            // reload. Lazy import to avoid a store-to-store cycle at module load.
            const { useDashboardsStore } = await import("./dashboards");
            void useDashboardsStore.getState().hydrate();
        }
        catch (err) {
            set({ pins: prev });
            throw err;
        }
    },
    demotePinFromPanel: async (pinId) => {
        const prev = get().pins;
        set({
            pins: prev.map((p) => p.id === pinId ? { ...p, is_main_panel: false } : p),
        });
        try {
            await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}/promote-panel`, { method: "DELETE" });
            const { useDashboardsStore } = await import("./dashboards");
            void useDashboardsStore.getState().hydrate();
        }
        catch (err) {
            set({ pins: prev });
            throw err;
        }
    },
    renamePin: async (pinId, displayLabel) => {
        const prev = get().pins;
        set({
            pins: prev.map((p) => p.id === pinId ? { ...p, display_label: displayLabel } : p),
        });
        try {
            await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ display_label: displayLabel }),
            });
        }
        catch (err) {
            set({ pins: prev });
            throw err;
        }
    },
    setPinScope: async (pinId, sourceBotId) => {
        const prev = get().pins;
        // Optimistic mirror of the backend's dual write (column + envelope).
        // Keeps the scope chip and the widget-auth flow consistent before the
        // round-trip returns.
        set({
            pins: prev.map((p) => {
                if (p.id !== pinId)
                    return p;
                const nextEnvelope = { ...(p.envelope ?? {}) };
                if (sourceBotId === null) {
                    delete nextEnvelope.source_bot_id;
                }
                else {
                    nextEnvelope.source_bot_id = sourceBotId;
                }
                return { ...p, source_bot_id: sourceBotId, envelope: nextEnvelope };
            }),
        });
        try {
            const updated = await apiFetch(`/api/v1/widgets/dashboard/pins/${pinId}/scope`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ source_bot_id: sourceBotId }),
            });
            set((s) => ({
                pins: s.pins.map((p) => (p.id === pinId ? updated : p)),
            }));
        }
        catch (err) {
            set({ pins: prev });
            throw err;
        }
    },
    applyLayout: async (items) => {
        if (items.length === 0)
            return;
        const prev = get().pins;
        const byId = new Map(items.map((it) => [it.id, it]));
        // Optimistic local write.
        set({
            pins: prev.map((p) => {
                const update = byId.get(p.id);
                if (!update)
                    return p;
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
        }
        catch (err) {
            set({ pins: prev });
            throw err;
        }
    },
    broadcastEnvelope: (toolName, envelope, opts) => {
        const key = dashboardEnvelopeKey(toolName, envelope);
        const update = {
            kind: opts?.kind ?? "tool_result",
            sourceToolName: toolName,
            sourceSignature: buildWidgetSyncSignature(toolName, opts?.widgetConfig),
            envelope,
        };
        set((s) => ({
            widgetEnvelopes: { ...s.widgetEnvelopes, [key]: update },
            pins: s.pins.map((p) => {
                if (dashboardEnvelopeKey(p.tool_name, p.envelope) !== key)
                    return p;
                return { ...p, envelope };
            }),
        }));
    },
    onChannelBroadcast: (toolName, envelope, opts) => {
        // Same mechanism — keyed by envelope identity. A no-op if no dashboard
        // pin matches the identity.
        get().broadcastEnvelope(toolName, envelope, opts);
    },
}));
