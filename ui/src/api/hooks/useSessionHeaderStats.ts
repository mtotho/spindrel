import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

interface ContextBudgetResponse {
  utilization: number | null;
  consumed_tokens: number | null;
  total_tokens: number | null;
  gross_prompt_tokens?: number | null;
  current_prompt_tokens?: number | null;
  cached_prompt_tokens?: number | null;
  completion_tokens?: number | null;
  context_profile?: string | null;
}

interface SessionDiagnosticsResponse {
  session_id: string;
  total_messages: number;
  total_user_turns: number;
  compaction: {
    enabled: boolean;
    interval: number | null;
    keep_turns: number | null;
    has_summary: boolean;
    has_watermark: boolean;
    watermark_created_at: string | null;
    user_turns_since_watermark: number;
    msgs_since_watermark: number;
    turns_until_next: number | null;
    last_compaction_at: string | null;
  };
}

export interface SessionHeaderStats {
  utilization: number | null;
  consumedTokens: number | null;
  totalTokens: number | null;
  grossPromptTokens: number | null;
  currentPromptTokens: number | null;
  cachedPromptTokens: number | null;
  completionTokens: number | null;
  contextProfile: string | null;
  turnsInContext: number | null;
  turnsUntilCompaction: number | null;
}

export function useSessionHeaderStats(
  channelId: string | undefined,
  sessionId?: string | null,
) {
  return useQuery<SessionHeaderStats>({
    queryKey: ["session-header-stats", channelId, sessionId ?? null],
    queryFn: async () => {
      const qs = new URLSearchParams();
      if (sessionId) qs.set("session_id", sessionId);
      const budget = await apiFetch<ContextBudgetResponse>(
        `/api/v1/channels/${channelId}/context-budget${qs.toString() ? `?${qs.toString()}` : ""}`,
      );
      const diagnostics = sessionId
        ? await apiFetch<SessionDiagnosticsResponse>(`/sessions/${sessionId}/context/diagnostics`)
        : null;
      return {
        utilization: budget.utilization,
        consumedTokens: budget.consumed_tokens,
        totalTokens: budget.total_tokens,
        grossPromptTokens: budget.gross_prompt_tokens ?? budget.consumed_tokens,
        currentPromptTokens: budget.current_prompt_tokens ?? budget.gross_prompt_tokens ?? budget.consumed_tokens,
        cachedPromptTokens: budget.cached_prompt_tokens ?? null,
        completionTokens: budget.completion_tokens ?? null,
        contextProfile: budget.context_profile ?? null,
        turnsInContext: diagnostics?.compaction.user_turns_since_watermark ?? null,
        turnsUntilCompaction: diagnostics?.compaction.turns_until_next ?? null,
      };
    },
    enabled: !!channelId,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
}
