import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type MissionStatus = "active" | "paused" | "completed" | "cancelled";
export type MissionScope = "workspace" | "channel";
export type MissionIntervalKind = "manual" | "preset" | "custom";

export interface WorkspaceMissionAssignment {
  id: string;
  mission_id: string;
  bot_id: string;
  bot_name: string;
  harness_runtime?: string | null;
  role: "owner" | "support";
  status: MissionStatus;
  target_channel_id?: string | null;
  last_update_at?: string | null;
  created_at?: string | null;
}

export interface WorkspaceMissionUpdate {
  id: string;
  mission_id: string;
  bot_id?: string | null;
  bot_name?: string | null;
  kind: "created" | "kickoff" | "tick" | "progress" | "result" | "error" | "manual";
  summary: string;
  next_actions: string[];
  task_id?: string | null;
  session_id?: string | null;
  correlation_id?: string | null;
  created_at?: string | null;
}

export interface WorkspaceMission {
  id: string;
  title: string;
  directive: string;
  status: MissionStatus;
  scope: MissionScope;
  channel_id?: string | null;
  channel_name?: string | null;
  play_key?: string | null;
  interval_kind: MissionIntervalKind;
  recurrence?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  fallback_models: Array<{ model: string; provider_id?: string | null }>;
  harness_effort?: string | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
  kickoff_task_id?: string | null;
  schedule_task_id?: string | null;
  last_task_id?: string | null;
  last_correlation_id?: string | null;
  last_update_at?: string | null;
  next_run_at?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  assignments: WorkspaceMissionAssignment[];
  updates: WorkspaceMissionUpdate[];
}

export interface MissionCreateInput {
  title: string;
  directive: string;
  scope: MissionScope;
  channel_id?: string | null;
  bot_id?: string | null;
  play_key?: string | null;
  interval_kind?: MissionIntervalKind;
  recurrence?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  harness_effort?: string | null;
  history_mode?: "none" | "recent" | "full" | null;
  history_recent_count?: number | null;
}

export const WORKSPACE_MISSIONS_KEY = ["workspace-missions"] as const;

export function useWorkspaceMissions(includeCompleted = false) {
  return useQuery({
    queryKey: [...WORKSPACE_MISSIONS_KEY, includeCompleted],
    queryFn: async () => {
      const params = new URLSearchParams({ include_completed: String(includeCompleted) });
      const res = await apiFetch<{ missions: WorkspaceMission[] }>(`/api/v1/workspace/missions?${params}`);
      return res.missions;
    },
    refetchInterval: 20_000,
    staleTime: 8_000,
    refetchOnWindowFocus: false,
  });
}

export function useCreateWorkspaceMission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: MissionCreateInput) => {
      const res = await apiFetch<{ mission: WorkspaceMission }>("/api/v1/workspace/missions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.mission;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_MISSIONS_KEY });
    },
  });
}

export function useRunWorkspaceMissionNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (missionId: string) => {
      const res = await apiFetch<{ mission: WorkspaceMission }>(`/api/v1/workspace/missions/${missionId}/run-now`, {
        method: "POST",
      });
      return res.mission;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_MISSIONS_KEY });
    },
  });
}

export function useSetWorkspaceMissionStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ missionId, status }: { missionId: string; status: MissionStatus }) => {
      const res = await apiFetch<{ mission: WorkspaceMission }>(`/api/v1/workspace/missions/${missionId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      return res.mission;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_MISSIONS_KEY });
    },
  });
}
