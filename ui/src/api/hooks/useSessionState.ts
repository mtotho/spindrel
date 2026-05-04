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
    const snapshotTurnIds = new Set<string>();
    for (const turn of query.data.active_turns) {
      snapshotTurnIds.add(turn.turn_id);
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

    const GHOST_GRACE_MS = 3000;
    const SSE_QUIET_MS = 180_000;
    const now = Date.now();
    const ch = store.getChannel(sessionId);
    for (const [turnId, turn] of Object.entries(ch.turns)) {
      if (snapshotTurnIds.has(turnId)) continue;
      if (now - turn.startedAt < GHOST_GRACE_MS) continue;
      if (now - turn.lastEventAt < SSE_QUIET_MS) continue;
      store.discardTurn(sessionId, turnId);
    }
  }, [sessionId, query.data, bots, primaryBotId]);

  return query;
}
