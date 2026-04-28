import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { UpcomingItem } from "./useUpcomingActivity";
import type {
  AttentionSeverity,
  AttentionAssignmentMode,
  WorkspaceAttentionItem,
} from "./useWorkspaceAttention";

export interface CommandCenterRecentEvent {
  type: "attention" | "assignment_report" | "heartbeat" | "task";
  status?: string | null;
  title: string;
  summary?: string | null;
  bot_id?: string | null;
  bot_name?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  occurred_at?: string | null;
  attention_item_id?: string | null;
  task_id?: string | null;
  heartbeat_id?: string | null;
  correlation_id?: string | null;
}

export interface CommandCenterBotRow {
  bot_id: string;
  bot_name: string;
  harness_runtime?: string | null;
  channels: Array<{ id: string; name: string }>;
  next_heartbeat_at?: string | null;
  heartbeat_channel_id?: string | null;
  heartbeat_channel_name?: string | null;
  assignments: WorkspaceAttentionItem[];
  active_assignment?: WorkspaceAttentionItem | null;
  queue_depth: number;
  upcoming: UpcomingItem[];
  recent: CommandCenterRecentEvent[];
}

export interface CommandCenterResponse {
  summary: {
    active_attention: number;
    assigned: number;
    blocked: number;
    upcoming: number;
    recent: number;
  };
  window: {
    recent_hours: number;
    upcoming_hours: number;
    recent_since: string;
    upcoming_until: string;
  };
  bots: CommandCenterBotRow[];
  attention: WorkspaceAttentionItem[];
  upcoming: UpcomingItem[];
  recent: CommandCenterRecentEvent[];
}

export interface CommandCenterIntakeInput {
  channel_id: string;
  title: string;
  message?: string;
  severity?: AttentionSeverity;
  next_steps?: string[];
  assign_bot_id?: string | null;
  assignment_mode?: AttentionAssignmentMode | null;
  assignment_instructions?: string | null;
}

export const COMMAND_CENTER_KEY = ["workspace-command-center"] as const;

export function useCommandCenter(recentHours = 24, upcomingHours = 24) {
  return useQuery({
    queryKey: [...COMMAND_CENTER_KEY, recentHours, upcomingHours],
    queryFn: () => {
      const params = new URLSearchParams({
        recent_hours: String(recentHours),
        upcoming_hours: String(upcomingHours),
      });
      return apiFetch<CommandCenterResponse>(`/api/v1/workspace/command-center?${params}`);
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

export function useCreateCommandCenterIntake() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CommandCenterIntakeInput) => {
      const res = await apiFetch<{ item: WorkspaceAttentionItem }>("/api/v1/workspace/command-center/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: COMMAND_CENTER_KEY });
      qc.invalidateQueries({ queryKey: ["workspace-attention"] });
    },
  });
}
