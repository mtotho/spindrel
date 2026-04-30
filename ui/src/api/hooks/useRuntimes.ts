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
  native_commands?: Array<{
    id: string;
    label: string;
    description: string;
    readonly: boolean;
    mutability?: "readonly" | "mutating" | "argument_sensitive" | string;
    aliases?: string[];
    interaction_kind?: string;
    fallback_behavior?: string;
  }>;
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

export interface HarnessRuntimeSummary {
  name: string;
  display_name: string;
  ok: boolean;
  detail: string;
  suggested_command?: string | null;
}

/**
 * Live list of registered agent-harness runtimes with their auth status.
 * Populates the bot editor's Runtime dropdown and the /admin/harnesses page.
 *
 * The list reflects which integrations are enabled (and thus had their
 * harness module imported on startup). Enabling a harness-providing
 * integration auto-registers its runtime; this query staleTime is short so
 * the dropdown reflects that without a manual refresh.
 */
export function useHarnessRuntimes() {
  return useQuery({
    queryKey: ["harness-runtimes"],
    queryFn: () =>
      apiFetch<{ runtimes: HarnessRuntimeSummary[] }>(
        "/api/v1/admin/harnesses",
      ),
    staleTime: 30 * 1000,
  });
}
