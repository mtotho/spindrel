import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useChatStore } from "../../stores/chat";
import { useBots } from "./useBots";
import type { ChannelStateSnapshot } from "./useChannelState";

export function useSessionState(sessionId: string | undefined, primaryBotId?: string) {
  const { data: bots } = useBots();

  const query = useQuery({
    queryKey: ["session-state", sessionId],
    queryFn: () =>
      apiFetch<ChannelStateSnapshot>(`/api/v1/sessions/${sessionId}/state`),
    enabled: !!sessionId,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (!sessionId || !query.data) return;
    const store = useChatStore.getState();
    const botName: Record<string, string> = {};
    if (bots) {
      for (const b of bots) botName[b.id] = b.name ?? b.id;
    }
    for (const turn of query.data.active_turns) {
      const toolCalls = turn.tool_calls.map((tc) => ({
        id: `${turn.turn_id}:snapshot:${tc.id}`,
        name: tc.tool_name,
        args: tc.arguments && Object.keys(tc.arguments).length > 0
          ? JSON.stringify(tc.arguments)
          : undefined,
        status: (tc.status === "error" || tc.status === "expired" ? "done" : tc.status) as
          "running" | "done" | "awaiting_approval" | "denied",
        approvalId: tc.approval_id ?? undefined,
        approvalReason: tc.approval_reason ?? undefined,
        capability: tc.capability ?? undefined,
        isError: tc.is_error || tc.status === "error" || tc.status === "expired" || undefined,
      }));
      const skills = turn.auto_injected_skills.map((s) => ({
        skillId: s.skill_id,
        skillName: s.skill_name,
        similarity: s.similarity,
        source: s.source,
      }));
      store.rehydrateTurn(
        sessionId,
        turn.turn_id,
        turn.bot_id,
        botName[turn.bot_id] ?? turn.bot_id,
        turn.bot_id === primaryBotId,
        toolCalls,
        skills,
      );
    }
  }, [sessionId, query.data, bots, primaryBotId]);

  return query;
}
