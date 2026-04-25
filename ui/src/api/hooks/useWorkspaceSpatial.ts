import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SpatialNode {
  id: string;
  channel_id: string | null;
  widget_pin_id: string | null;
  world_x: number;
  world_y: number;
  world_w: number;
  world_h: number;
  z_index: number;
  seed_index: number | null;
  pinned_at: string | null;
  updated_at: string | null;
}

interface NodesResponse {
  nodes: SpatialNode[];
}

const NODES_KEY = ["workspace-spatial-nodes"] as const;

/** List spatial canvas nodes. The server upserts a node row for every
 *  channel that doesn't yet have one, so this is the only call needed to
 *  hydrate the canvas. */
export function useSpatialNodes() {
  return useQuery({
    queryKey: NODES_KEY,
    queryFn: async () => {
      const res = await apiFetch<NodesResponse>("/api/v1/workspace/spatial/nodes");
      return res.nodes;
    },
  });
}

interface UpdateNodeBody {
  world_x?: number;
  world_y?: number;
  world_w?: number;
  world_h?: number;
  z_index?: number;
}

/** PATCH a node's position / size / z-index. Optimistic — patches local
 *  cache before the server roundtrip so drag feels instant. */
export function useUpdateSpatialNode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { nodeId: string; body: UpdateNodeBody }) => {
      const res = await apiFetch<{ node: SpatialNode }>(
        `/api/v1/workspace/spatial/nodes/${params.nodeId}`,
        { method: "PATCH", body: JSON.stringify(params.body) },
      );
      return res.node;
    },
    onMutate: async ({ nodeId, body }) => {
      await qc.cancelQueries({ queryKey: NODES_KEY });
      const prev = qc.getQueryData<SpatialNode[]>(NODES_KEY);
      qc.setQueryData<SpatialNode[]>(NODES_KEY, (old) =>
        (old ?? []).map((n) =>
          n.id === nodeId ? { ...n, ...body } : n,
        ),
      );
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(NODES_KEY, ctx.prev);
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
    mutationFn: async (nodeId: string) => {
      await apiFetch<void>(`/api/v1/workspace/spatial/nodes/${nodeId}`, {
        method: "DELETE",
      });
      return nodeId;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
    },
  });
}

interface PinWidgetBody {
  source_kind: "channel" | "adhoc";
  tool_name: string;
  envelope: Record<string, unknown>;
  source_channel_id?: string;
  source_bot_id?: string | null;
  tool_args?: Record<string, unknown>;
  widget_config?: Record<string, unknown>;
  widget_origin?: Record<string, unknown>;
  display_label?: string;
  world_x?: number;
  world_y?: number;
  world_w?: number;
  world_h?: number;
}

/** Atomically pin a widget to the workspace canvas. Server creates the
 *  pin + node in one transaction; orphan pin on partial failure is not
 *  possible. */
export function usePinWidgetToCanvas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PinWidgetBody) => {
      return apiFetch<{ pin: unknown; node: SpatialNode }>(
        "/api/v1/workspace/spatial/widget-pins",
        { method: "POST", body: JSON.stringify(body) },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
      // Pin lists for the workspace:spatial slug are intentionally hidden
      // from user dashboard listings. If a future surface lists them
      // explicitly, invalidate that key here.
    },
  });
}
