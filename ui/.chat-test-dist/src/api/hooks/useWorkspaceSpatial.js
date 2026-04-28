import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
export const NODES_KEY = ["workspace-spatial-nodes"];
/** List spatial canvas nodes. The server upserts a node row for every
 *  channel that doesn't yet have one, so this is the only call needed to
 *  hydrate the canvas. */
export function useSpatialNodes() {
    return useQuery({
        queryKey: NODES_KEY,
        queryFn: async () => {
            const res = await apiFetch("/api/v1/workspace/spatial/nodes");
            return res.nodes;
        },
    });
}
/** PATCH a node's position / size / z-index. Optimistic — patches local
 *  cache before the server roundtrip so drag feels instant. */
export function useUpdateSpatialNode() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (params) => {
            const res = await apiFetch(`/api/v1/workspace/spatial/nodes/${params.nodeId}`, { method: "PATCH", body: JSON.stringify(params.body) });
            return res.node;
        },
        onMutate: async ({ nodeId, body }) => {
            await qc.cancelQueries({ queryKey: NODES_KEY });
            const prev = qc.getQueryData(NODES_KEY);
            qc.setQueryData(NODES_KEY, (old) => (old ?? []).map((n) => n.id === nodeId ? { ...n, ...body } : n));
            return { prev };
        },
        onError: (_err, _vars, ctx) => {
            if (ctx?.prev)
                qc.setQueryData(NODES_KEY, ctx.prev);
        },
        onSettled: () => {
            qc.invalidateQueries({ queryKey: NODES_KEY });
        },
    });
}
/** Remove a spatial node. For widget nodes this also deletes the
 *  underlying ``widget_dashboard_pins`` row server-side; for channel
 *  nodes the next list call re-seeds at a new phyllotaxis slot ("reset
 *  position" gesture). */
export function useDeleteSpatialNode() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (nodeId) => {
            await apiFetch(`/api/v1/workspace/spatial/nodes/${nodeId}`, {
                method: "DELETE",
            });
            return nodeId;
        },
        onMutate: async (nodeId) => {
            await qc.cancelQueries({ queryKey: NODES_KEY });
            const prev = qc.getQueryData(NODES_KEY);
            qc.setQueryData(NODES_KEY, (old) => (old ?? []).filter((n) => n.id !== nodeId));
            return { prev };
        },
        onError: (_err, _nodeId, ctx) => {
            if (ctx?.prev)
                qc.setQueryData(NODES_KEY, ctx.prev);
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: NODES_KEY });
        },
        onSettled: () => {
            qc.invalidateQueries({ queryKey: NODES_KEY });
        },
    });
}
/** Find the spatial node for a widget pin matching the given identity key
 *  (built from `envelopeIdentityKey`). Returns the node or undefined.
 *  Use to detect "already on canvas" and offer a remove-from-canvas
 *  affordance instead of creating a duplicate.
 */
export function useFindCanvasNodeByIdentity(identityKey, identityFor) {
    return useFindCanvasNodesByIdentity(identityKey, identityFor)[0];
}
export function useFindCanvasNodesByIdentity(identityKey, identityFor) {
    const { data: nodes } = useSpatialNodes();
    if (!identityKey || !nodes)
        return [];
    return nodes.filter((n) => n.pin && identityFor(n.pin) === identityKey);
}
/** Pick the spatial node row for a given fixed landmark. Returns undefined
 *  until the canvas list query resolves. World coords on the row are the
 *  source of truth; defaults in `spatialGeometry.ts` only apply on the
 *  server side at first-seed time. */
export function useLandmarkNode(kind) {
    const { data: nodes } = useSpatialNodes();
    if (!nodes)
        return undefined;
    return nodes.find((n) => n.landmark_kind === kind);
}
/** Live world position of a landmark, with fallback defaults that mirror
 *  the server-side seed coords. Use this at any callsite that needs to
 *  reason about a landmark's current location (orbit math, fly-to camera,
 *  lens projection) so the position tracks user drags. */
export function landmarkPositionFromNodes(nodes, kind, fallbackX, fallbackY) {
    const row = nodes?.find((n) => n.landmark_kind === kind);
    return { x: row?.world_x ?? fallbackX, y: row?.world_y ?? fallbackY };
}
export function useFindCanvasNodesByPinPredicate(predicate) {
    const { data: nodes } = useSpatialNodes();
    if (!nodes)
        return [];
    return nodes.filter((n) => n.pin && predicate(n.pin));
}
/** Atomically pin a widget to the workspace canvas. Server creates the
 *  pin + node in one transaction; orphan pin on partial failure is not
 *  possible. */
export function usePinWidgetToCanvas() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (body) => {
            return apiFetch("/api/v1/workspace/spatial/widget-pins", { method: "POST", body: JSON.stringify(body) });
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: NODES_KEY });
            // Pin lists for the workspace:spatial slug are intentionally hidden
            // from user dashboard listings. If a future surface lists them
            // explicitly, invalidate that key here.
        },
    });
}
/** Pin a `widget_presets[*]` entry to the workspace canvas. Server runs
 *  the preset preview pipeline and atomically creates the pin + node. */
export function usePinPresetToCanvas() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (body) => {
            return apiFetch("/api/v1/workspace/spatial/preset-pins", { method: "POST", body: JSON.stringify(body) });
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: NODES_KEY });
        },
    });
}
export function useSpatialBotPolicy(channelId, botId) {
    return useQuery({
        queryKey: ["channel-spatial-bot-policy", channelId, botId],
        queryFn: async () => {
            const res = await apiFetch(`/api/v1/channels/${channelId}/spatial-bots/${encodeURIComponent(botId)}`);
            return res.policy;
        },
        enabled: !!channelId && !!botId,
    });
}
export function useUpdateSpatialBotPolicy(channelId, botId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (body) => {
            const res = await apiFetch(`/api/v1/channels/${channelId}/spatial-bots/${encodeURIComponent(botId)}`, { method: "PATCH", body: JSON.stringify(body) });
            return res.policy;
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ["channel-spatial-bot-policy", channelId, botId] });
        },
    });
}
