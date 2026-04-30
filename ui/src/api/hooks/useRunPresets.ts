import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface RunPresetTaskDefaults {
  title: string;
  prompt: string;
  scheduled_at?: string | null;
  recurrence?: string | null;
  task_type: string;
  trigger_config: Record<string, any>;
  skills: string[];
  tools: string[];
  post_final_to_channel: boolean;
  history_mode: "none" | "recent" | "full";
  history_recent_count: number;
  skip_tool_approval: boolean;
  session_target?: Record<string, any> | null;
  project_instance?: Record<string, any> | null;
  allow_issue_reporting?: boolean | null;
  harness_effort?: string | null;
  max_run_seconds?: number | null;
}

export interface RunPresetHeartbeatDefaults {
  append_spatial_prompt: boolean;
  append_spatial_map_overview: boolean;
  include_pinned_widgets: boolean;
  execution_config: Record<string, any>;
  spatial_policy: Record<string, any>;
}

export interface RunPreset {
  id: string;
  title: string;
  description: string;
  surface: string;
  task_defaults?: RunPresetTaskDefaults | null;
  heartbeat_defaults?: RunPresetHeartbeatDefaults | null;
}

export function useRunPresets(surface?: string) {
  const query = surface ? `?surface=${encodeURIComponent(surface)}` : "";
  return useQuery({
    queryKey: ["admin-run-presets", surface ?? "all"],
    queryFn: () => apiFetch<{ presets: RunPreset[] }>(`/api/v1/admin/run-presets${query}`),
    staleTime: 5 * 60_000,
  });
}
