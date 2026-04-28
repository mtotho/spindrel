import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WorkspaceAttentionItem } from "./useWorkspaceAttention";
import type { MissionIntervalKind, MissionScope, WorkspaceMission, WorkspaceMissionAssignment, WorkspaceMissionUpdate } from "./useWorkspaceMissions";
import { WORKSPACE_MISSIONS_KEY } from "./useWorkspaceMissions";

export type SpatialReadiness = "ready" | "far" | "blocked" | "unknown";

export interface MissionControlSpatialPolicy {
  enabled: boolean;
  allow_movement: boolean;
  allow_nearby_inspect: boolean;
  allow_moving_spatial_objects: boolean;
  step_world_units: number;
  awareness_radius_steps: number;
  awareness_radius_world: number;
  tug_radius_steps: number;
  tug_radius_world: number;
  minimum_clearance_steps: number;
}

export interface MissionControlSpatialAdvisory {
  bot_id: string;
  bot_node_id?: string | null;
  target_node_id?: string | null;
  target_channel_id?: string | null;
  target_channel_name?: string | null;
  center_distance?: number | null;
  edge_distance?: number | null;
  policy: MissionControlSpatialPolicy;
  status: SpatialReadiness;
  reason: string;
}

export interface MissionControlNearestObject {
  node_id: string;
  kind: "bot" | "channel" | "widget" | "landmark" | "object";
  label: string;
  channel_id?: string | null;
  widget_pin_id?: string | null;
  bot_id?: string | null;
  center_distance: number;
  edge_distance: number;
}

export interface MissionControlBotNode {
  id: string;
  bot_id?: string | null;
  world_x: number;
  world_y: number;
  world_w: number;
  world_h: number;
}

export interface MissionControlAttentionSignal {
  id: string;
  title: string;
  severity: WorkspaceAttentionItem["severity"];
  status: WorkspaceAttentionItem["status"];
  assignment_status?: WorkspaceAttentionItem["assignment_status"] | null;
  channel_id?: string | null;
  channel_name?: string | null;
  latest_correlation_id?: string | null;
  last_seen_at?: string | null;
}

export interface MissionControlMissionRow {
  mission: WorkspaceMission;
  assignment: WorkspaceMissionAssignment;
  latest_update?: WorkspaceMissionUpdate | null;
  spatial_advisory: MissionControlSpatialAdvisory;
}

export interface MissionControlLane {
  bot_id: string;
  bot_name: string;
  harness_runtime?: string | null;
  bot_node?: MissionControlBotNode | null;
  nearest_objects: MissionControlNearestObject[];
  missions: MissionControlMissionRow[];
  attention_signals: MissionControlAttentionSignal[];
  warning_count: number;
}

export interface MissionControlRecentUpdate {
  mission_id: string;
  mission_title: string;
  update: WorkspaceMissionUpdate;
}

export interface MissionControlAssistantBrief {
  id: string;
  summary: string;
  next_focus: string;
  confidence: "low" | "medium" | "high";
  user_instruction?: string | null;
  grounding_summary: Record<string, unknown>;
  ai_model?: string | null;
  ai_provider_id?: string | null;
  created_by?: string | null;
  created_at?: string | null;
}

export interface MissionControlDraft {
  id: string;
  status: "draft" | "accepted" | "dismissed";
  source: "ai" | "user";
  title: string;
  directive: string;
  rationale?: string | null;
  scope: MissionScope;
  bot_id?: string | null;
  bot_name?: string | null;
  target_channel_id?: string | null;
  target_channel_name?: string | null;
  interval_kind: MissionIntervalKind;
  recurrence?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  harness_effort?: string | null;
  grounding_summary: Record<string, unknown>;
  ai_model?: string | null;
  ai_provider_id?: string | null;
  user_instruction?: string | null;
  accepted_mission_id?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MissionControlDraftUpdateInput {
  title?: string;
  directive?: string;
  rationale?: string | null;
  scope?: MissionScope;
  bot_id?: string | null;
  target_channel_id?: string | null;
  interval_kind?: MissionIntervalKind;
  recurrence?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  harness_effort?: string | null;
}

export interface MissionControlResponse {
  generated_at?: string | null;
  summary: {
    active_missions: number;
    paused_missions: number;
    active_bots: number;
    attention_signals: number;
    assigned_attention: number;
    spatial_warnings: number;
    recent_updates: number;
  };
  missions: WorkspaceMission[];
  lanes: MissionControlLane[];
  attention: WorkspaceAttentionItem[];
  unassigned_attention: MissionControlAttentionSignal[];
  recent_updates: MissionControlRecentUpdate[];
  mission_rows: Record<string, MissionControlMissionRow>;
  assistant_brief?: MissionControlAssistantBrief | null;
  drafts: MissionControlDraft[];
}

export const MISSION_CONTROL_KEY = ["workspace-mission-control"] as const;

export function useMissionControl(includeCompleted = false) {
  return useQuery({
    queryKey: [...MISSION_CONTROL_KEY, includeCompleted],
    queryFn: async () => {
      const params = new URLSearchParams({ include_completed: String(includeCompleted) });
      return apiFetch<MissionControlResponse>(`/api/v1/workspace/mission-control?${params}`);
    },
    refetchInterval: 20_000,
    staleTime: 8_000,
    refetchOnWindowFocus: false,
  });
}

function useInvalidateMissionControl() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: MISSION_CONTROL_KEY });
    qc.invalidateQueries({ queryKey: WORKSPACE_MISSIONS_KEY });
  };
}

export function useRefreshMissionControlAi() {
  const invalidate = useInvalidateMissionControl();
  return useMutation({
    mutationFn: async (instruction?: string) => apiFetch<{ assistant_brief: MissionControlAssistantBrief; drafts: MissionControlDraft[] }>("/api/v1/workspace/mission-control/ai/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction: instruction || null }),
    }),
    onSettled: invalidate,
  });
}

export function useAskMissionControlAi() {
  const invalidate = useInvalidateMissionControl();
  return useMutation({
    mutationFn: async (instruction: string) => apiFetch<{ assistant_brief: MissionControlAssistantBrief; drafts: MissionControlDraft[] }>("/api/v1/workspace/mission-control/ai/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }),
    onSettled: invalidate,
  });
}

export function useUpdateMissionControlDraft() {
  const invalidate = useInvalidateMissionControl();
  return useMutation({
    mutationFn: async ({ draftId, patch }: { draftId: string; patch: MissionControlDraftUpdateInput }) => {
      const res = await apiFetch<{ draft: MissionControlDraft }>(`/api/v1/workspace/mission-control/drafts/${draftId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      return res.draft;
    },
    onSettled: invalidate,
  });
}

export function useAcceptMissionControlDraft() {
  const invalidate = useInvalidateMissionControl();
  return useMutation({
    mutationFn: async (draftId: string) => apiFetch<{ draft: MissionControlDraft; mission: WorkspaceMission }>(`/api/v1/workspace/mission-control/drafts/${draftId}/accept`, {
      method: "POST",
    }),
    onSettled: invalidate,
  });
}

export function useDismissMissionControlDraft() {
  const invalidate = useInvalidateMissionControl();
  return useMutation({
    mutationFn: async (draftId: string) => {
      const res = await apiFetch<{ draft: MissionControlDraft }>(`/api/v1/workspace/mission-control/drafts/${draftId}/dismiss`, {
        method: "POST",
      });
      return res.draft;
    },
    onSettled: invalidate,
  });
}
