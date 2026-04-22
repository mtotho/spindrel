import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
export function useLogs(params) {
    const qs = new URLSearchParams();
    if (params.event_type)
        qs.set("event_type", params.event_type);
    if (params.bot_id)
        qs.set("bot_id", params.bot_id);
    if (params.session_id)
        qs.set("session_id", params.session_id);
    if (params.channel_id)
        qs.set("channel_id", params.channel_id);
    if (params.page)
        qs.set("page", String(params.page));
    if (params.page_size)
        qs.set("page_size", String(params.page_size));
    const query = qs.toString();
    return useQuery({
        queryKey: ["admin-logs", params],
        queryFn: () => apiFetch(`/api/v1/admin/logs${query ? `?${query}` : ""}`),
    });
}
export function useTrace(correlationId) {
    return useQuery({
        queryKey: ["admin-trace", correlationId],
        queryFn: () => apiFetch(`/api/v1/admin/traces/${correlationId}`),
        enabled: !!correlationId,
        // Auto-poll while the trace is still growing. If the most recent event
        // is < 5s old we keep polling every 2s — handles slow-running agent
        // steps (e.g. analyze pipelines that take minutes) without the user
        // needing to refresh. Quiescent traces stop polling automatically.
        refetchInterval: (query) => {
            const data = query.state.data;
            if (!data || !data.events || data.events.length === 0)
                return false;
            const last = data.events[data.events.length - 1];
            const ts = last.created_at ? Date.parse(last.created_at) : NaN;
            if (!Number.isFinite(ts))
                return false;
            const ageMs = Date.now() - ts;
            return ageMs < 5000 ? 2000 : false;
        },
    });
}
export function useTraces(params, enabled = true) {
    const qs = new URLSearchParams();
    if (params.count)
        qs.set("count", String(params.count));
    if (params.bot_id)
        qs.set("bot_id", params.bot_id);
    if (params.source_type)
        qs.set("source_type", params.source_type);
    if (params.before)
        qs.set("before", params.before);
    const query = qs.toString();
    return useQuery({
        queryKey: ["admin-traces", params],
        queryFn: () => apiFetch(`/api/v1/admin/traces${query ? `?${query}` : ""}`),
        enabled,
    });
}
