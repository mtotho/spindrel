import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SessionConfigOverhead {
  lines: Array<{ label: string; chars: number; tokens: number }>;
  total_chars: number;
  approx_tokens: number;
  context_window: number | null;
  overhead_pct: number | null;
  disclaimer: string;
}

/** Mirror of ``useChannelConfigOverhead`` for ephemeral / sub-sessions. */
export function useSessionConfigOverhead(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["session-config-overhead", sessionId],
    queryFn: () =>
      apiFetch<SessionConfigOverhead>(
        `/api/v1/sessions/${sessionId}/config-overhead`,
      ),
    enabled: !!sessionId,
    staleTime: 60_000,
  });
}
