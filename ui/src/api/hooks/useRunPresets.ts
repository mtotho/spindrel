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
}

export interface RunPreset {
  id: string;
  title: string;
  description: string;
  surface: string;
  task_defaults: RunPresetTaskDefaults;
}

export function useRunPresets(surface?: string) {
  const query = surface ? `?surface=${encodeURIComponent(surface)}` : "";
  return useQuery({
    queryKey: ["admin-run-presets", surface ?? "all"],
    queryFn: () => apiFetch<{ presets: RunPreset[] }>(`/api/v1/admin/run-presets${query}`),
    staleTime: 5 * 60_000,
  });
}
