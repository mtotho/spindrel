import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

/** Inline pin payload embedded by the server when a node has a
 *  `widget_pin_id`. Contains everything the client needs to render the
 *  widget tile without a second roundtrip — envelope, contract/presentation
 *  snapshots, source bot. Untyped contents (Record) since the snapshots
 *  evolve and the canvas only reads a few top-level fields. */
export interface SpatialNodePin {
  id: string;
  tool_name: string;
  display_label: string | null;
  source_bot_id: string | null;
  source_channel_id: string | null;
  envelope: Record<string, unknown>;
  widget_origin?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown>;
  panel_title?: string | null;
}

export interface SpatialNode {
  id: string;
  channel_id: string | null;
  widget_pin_id: string | null;
  bot_id: string | null;
  world_x: number;
  world_y: number;
  world_w: number;
  world_h: number;
  z_index: number;
  seed_index: number | null;
  pinned_at: string | null;
  updated_at: string | null;
  last_movement?: {
    kind?: string;
    actor_bot_id?: string;
    channel_id?: string;
    target_node_id?: string | null;
    from?: { x: number; y: number };
    to?: { x: number; y: number };
    reason?: string | null;
    created_at?: string;
    expires_at?: string;
    ttl_minutes?: number;
  } | null;
  bot?: {
    id: string;
    name?: string;
    display_name?: string | null;
    avatar_url?: string | null;
    avatar_emoji?: string | null;
  };
  /** Present only when `widget_pin_id` is set. */
  pin?: SpatialNodePin;
}

export interface SpatialBotPolicy {
  enabled: boolean;
  allow_movement: boolean;
  step_world_units: number;
  max_move_steps_per_turn: number;
  awareness_radius_steps: number;
  nearest_neighbor_floor: number;
  allow_moving_spatial_objects: boolean;
  allow_spatial_widget_management: boolean;
  tug_radius_steps: number;
  max_tug_steps_per_turn: number;
  allow_nearby_inspect: boolean;
  movement_trace_ttl_minutes: number;
}

interface NodesResponse {
  nodes: SpatialNode[];
}

export const NODES_KEY = ["workspace-spatial-nodes"] as const;

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

/** Find the spatial node for a widget pin matching the given identity key
 *  (built from `envelopeIdentityKey`). Returns the node or undefined.
 *  Use to detect "already on canvas" and offer a remove-from-canvas
 *  affordance instead of creating a duplicate.
 */
export function useFindCanvasNodeByIdentity(
  identityKey: string | null,
  identityFor: (pin: SpatialNodePin) => string,
): SpatialNode | undefined {
  const { data: nodes } = useSpatialNodes();
  if (!identityKey || !nodes) return undefined;
  return nodes.find((n) => n.pin && identityFor(n.pin) === identityKey);
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

export function useSpatialBotPolicy(channelId: string | undefined, botId: string | undefined) {
  return useQuery({
    queryKey: ["channel-spatial-bot-policy", channelId, botId],
    queryFn: async () => {
      const res = await apiFetch<{ policy: SpatialBotPolicy }>(
        `/api/v1/channels/${channelId}/spatial-bots/${encodeURIComponent(botId!)}`,
      );
      return res.policy;
    },
    enabled: !!channelId && !!botId,
  });
}

export function useUpdateSpatialBotPolicy(channelId: string | undefined, botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<SpatialBotPolicy>) => {
      const res = await apiFetch<{ policy: SpatialBotPolicy }>(
        `/api/v1/channels/${channelId}/spatial-bots/${encodeURIComponent(botId!)}`,
        { method: "PATCH", body: JSON.stringify(body) },
      );
      return res.policy;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-spatial-bot-policy", channelId, botId] });
    },
  });
}
