import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { Channel } from "../../types/api";

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
  widget_instance_id?: string | null;
  envelope: Record<string, unknown>;
  widget_origin?: Record<string, unknown> | null;
  widget_config?: Record<string, unknown>;
  panel_title?: string | null;
}

export type LandmarkKind =
  | "now_well"
  | "memory_observatory"
  | "attention_hub"
  | "daily_health";

export interface SpatialNode {
  id: string;
  channel_id: string | null;
  project_id: string | null;
  widget_pin_id: string | null;
  bot_id: string | null;
  landmark_kind: LandmarkKind | null;
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
  /** Bounded log of recent prior positions for the comet-tail trail layer.
   *  Newest entry is the position right before the latest move; combine with
   *  current `world_x` / `world_y` to draw the path. Pruned server-side to
   *  the last 72h / 30 entries. */
  position_history?: Array<{
    x: number;
    y: number;
    ts: string;
    actor?: string | null;
  }>;
  bot?: {
    id: string;
    name?: string;
    display_name?: string | null;
    avatar_url?: string | null;
    avatar_emoji?: string | null;
  };
  project?: {
    id: string;
    workspace_id: string;
    name: string;
    slug?: string | null;
    root_path?: string | null;
    attached_channel_count?: number;
  };
  /** Present only when `widget_pin_id` is set. */
  pin?: SpatialNodePin;
}

export interface SpatialBotPolicy {
  enabled: boolean;
  allow_movement: boolean;
  step_world_units: number;
  max_move_steps_per_turn: number;
  minimum_clearance_steps: number;
  awareness_radius_steps: number;
  nearest_neighbor_floor: number;
  allow_moving_spatial_objects: boolean;
  allow_spatial_widget_management: boolean;
  allow_attention_beacons: boolean;
  allow_map_view: boolean;
  tug_radius_steps: number;
  max_tug_steps_per_turn: number;
  allow_nearby_inspect: boolean;
  movement_trace_ttl_minutes: number;
}

interface NodesResponse {
  nodes: SpatialNode[];
}

export const NODES_KEY = ["workspace-spatial-nodes"] as const;
export const BOOTSTRAP_KEY = ["workspace-spatial-bootstrap"] as const;

export interface SpatialCanvasBootstrap {
  nodes: SpatialNode[];
  channels: Channel[];
  bots: Array<{
    id: string;
    name?: string;
    display_name?: string | null;
    avatar_url?: string | null;
    avatar_emoji?: string | null;
  }>;
}

export function useSpatialCanvasBootstrap() {
  return useQuery({
    queryKey: BOOTSTRAP_KEY,
    queryFn: () => apiFetch<SpatialCanvasBootstrap>("/api/v1/workspace/spatial/bootstrap"),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

/** List spatial canvas nodes. The server upserts a node row for every
 *  channel that doesn't yet have one, so this is the only call needed to
 *  hydrate the canvas. */
export function useSpatialNodes(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: NODES_KEY,
    queryFn: async () => {
      const res = await apiFetch<NodesResponse>("/api/v1/workspace/spatial/nodes");
      return res.nodes;
    },
    enabled: options?.enabled ?? true,
    refetchOnWindowFocus: false,
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
      const prevBootstrap = qc.getQueryData<SpatialCanvasBootstrap>(BOOTSTRAP_KEY);
      qc.setQueryData<SpatialNode[]>(NODES_KEY, (old) =>
        (old ?? []).map((n) =>
          n.id === nodeId ? { ...n, ...body } : n,
        ),
      );
      qc.setQueryData<SpatialCanvasBootstrap>(BOOTSTRAP_KEY, (old) =>
        old ? {
          ...old,
          nodes: old.nodes.map((n) => (n.id === nodeId ? { ...n, ...body } : n)),
        } : old,
      );
      return { prev, prevBootstrap };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(NODES_KEY, ctx.prev);
      if (ctx?.prevBootstrap) qc.setQueryData(BOOTSTRAP_KEY, ctx.prevBootstrap);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
      qc.invalidateQueries({ queryKey: BOOTSTRAP_KEY });
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
    onMutate: async (nodeId) => {
      await qc.cancelQueries({ queryKey: NODES_KEY });
      const prev = qc.getQueryData<SpatialNode[]>(NODES_KEY);
      const prevBootstrap = qc.getQueryData<SpatialCanvasBootstrap>(BOOTSTRAP_KEY);
      qc.setQueryData<SpatialNode[]>(NODES_KEY, (old) =>
        (old ?? []).filter((n) => n.id !== nodeId),
      );
      qc.setQueryData<SpatialCanvasBootstrap>(BOOTSTRAP_KEY, (old) =>
        old ? { ...old, nodes: old.nodes.filter((n) => n.id !== nodeId) } : old,
      );
      return { prev, prevBootstrap };
    },
    onError: (_err, _nodeId, ctx) => {
      if (ctx?.prev) qc.setQueryData(NODES_KEY, ctx.prev);
      if (ctx?.prevBootstrap) qc.setQueryData(BOOTSTRAP_KEY, ctx.prevBootstrap);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
      qc.invalidateQueries({ queryKey: BOOTSTRAP_KEY });
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
      qc.invalidateQueries({ queryKey: BOOTSTRAP_KEY });
    },
  });
}

interface PinWidgetBody {
  source_dashboard_pin_id?: string;
  source_kind?: "channel" | "adhoc";
  tool_name?: string;
  envelope?: Record<string, unknown>;
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
  return useFindCanvasNodesByIdentity(identityKey, identityFor)[0];
}

export function useFindCanvasNodesByIdentity(
  identityKey: string | null,
  identityFor: (pin: SpatialNodePin) => string,
): SpatialNode[] {
  const { data: nodes } = useSpatialNodes();
  if (!identityKey || !nodes) return [];
  return nodes.filter((n) => n.pin && identityFor(n.pin) === identityKey);
}

/** Pick the spatial node row for a given fixed landmark. Returns undefined
 *  until the canvas list query resolves. World coords on the row are the
 *  source of truth; defaults in `spatialGeometry.ts` only apply on the
 *  server side at first-seed time. */
export function useLandmarkNode(kind: LandmarkKind): SpatialNode | undefined {
  const { data: nodes } = useSpatialNodes();
  if (!nodes) return undefined;
  return nodes.find((n) => n.landmark_kind === kind);
}

/** Live world position of a landmark, with fallback defaults that mirror
 *  the server-side seed coords. Use this at any callsite that needs to
 *  reason about a landmark's current location (orbit math, fly-to camera,
 *  lens projection) so the position tracks user drags. */
export function landmarkPositionFromNodes(
  nodes: SpatialNode[] | undefined,
  kind: LandmarkKind,
  fallbackX: number,
  fallbackY: number,
): { x: number; y: number } {
  const row = nodes?.find((n) => n.landmark_kind === kind);
  return { x: row?.world_x ?? fallbackX, y: row?.world_y ?? fallbackY };
}

export function useFindCanvasNodesByPinPredicate(
  predicate: (pin: SpatialNodePin) => boolean,
): SpatialNode[] {
  const { data: nodes } = useSpatialNodes();
  if (!nodes) return [];
  return nodes.filter((n) => n.pin && predicate(n.pin));
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
      qc.invalidateQueries({ queryKey: BOOTSTRAP_KEY });
      // Pin lists for the workspace:spatial slug are intentionally hidden
      // from user dashboard listings. If a future surface lists them
      // explicitly, invalidate that key here.
    },
  });
}

export interface PinPresetBody {
  preset_id: string;
  config?: Record<string, unknown> | null;
  source_bot_id?: string | null;
  source_channel_id?: string | null;
  display_label?: string | null;
  world_x?: number | null;
  world_y?: number | null;
  world_w?: number | null;
  world_h?: number | null;
}

/** Pin a `widget_presets[*]` entry to the workspace canvas. Server runs
 *  the preset preview pipeline and atomically creates the pin + node. */
export function usePinPresetToCanvas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: PinPresetBody) => {
      return apiFetch<{ pin: { id: string }; node: SpatialNode }>(
        "/api/v1/workspace/spatial/preset-pins",
        { method: "POST", body: JSON.stringify(body) },
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: NODES_KEY });
      qc.invalidateQueries({ queryKey: BOOTSTRAP_KEY });
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
