import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface HarnessSlashCommandPolicy {
  allowed_command_ids: string[];
}

export interface RuntimeCapabilities {
  name: string;
  display_name: string;
  supported_models: string[];
  model_options: Array<{
    id: string;
    label?: string | null;
    effort_values: string[];
    default_effort?: string | null;
  }>;
  /** Live list from the runtime adapter — what the picker should show. */
  available_models: string[];
  model_is_freeform: boolean;
  effort_values: string[];
  approval_modes: string[];
  slash_policy: HarnessSlashCommandPolicy;
  native_compaction: boolean;
  context_window_tokens?: number | null;
}

/**
 * Static control surface for a harness runtime — what model knobs, effort
 * values, approval modes, and slash commands the UI should expose for
 * sessions on this runtime.
 *
 * Capabilities are static per process, so we cache for an hour. Bumping a
 * runtime's capabilities requires a process restart anyway.
 */
export function useRuntimeCapabilities(
  runtimeName: string | null | undefined,
) {
  return useQuery({
    queryKey: ["runtime-capabilities", runtimeName],
    queryFn: () =>
      apiFetch<RuntimeCapabilities>(
        `/api/v1/runtimes/${runtimeName}/capabilities`,
      ),
    enabled: !!runtimeName,
    staleTime: 60 * 60 * 1000,
  });
}
