import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useChatStore } from "../../stores/chat";
import { useBots } from "./useBots";
import type { ToolApproval } from "./useApprovals";

/** One in-flight turn the UI should rehydrate on mount. `turn_id` IS the
 * correlation_id that threads through SSE — see turn_worker.py:94. */
export interface ActiveTurnToolCall {
  id: string;
  tool_name: string;
  arguments: Record<string, any>;
  status: "running" | "awaiting_approval" | "done" | "error" | "denied" | "expired";
  is_error: boolean;
  approval_id: string | null;
  approval_reason: string | null;
  capability: {
    id: string;
    name: string;
    description: string;
    tools_count: number;
    skills_count: number;
  } | null;
}

export interface ActiveTurnSkill {
  skill_id: string;
  skill_name: string;
  similarity: number;
  source: string;
}

export interface ActiveTurn {
  turn_id: string;
  bot_id: string;
  is_primary: boolean;
  tool_calls: ActiveTurnToolCall[];
  auto_injected_skills: ActiveTurnSkill[];
}

export interface ChannelStateSnapshot {
  active_turns: ActiveTurn[];
  pending_approvals: ToolApproval[];
}

/** Fetch the channel's in-flight state snapshot and seed the chat store.
 *
 * Paired with useChannelEvents: the SSE stream carries deltas, this carries
 * the baseline. On mount / tab-wake / reconnect the UI calls this once; the
 * store's `rehydrateTurn` action seeds turns whose SSE events predate the
 * current subscription (or were evicted by the 256-event replay buffer). */
export function useChannelState(channelId: string | undefined, primaryBotId?: string) {
  const queryClient = useQueryClient();
  const { data: bots } = useBots();

  const query = useQuery({
    queryKey: ["channel-state", channelId],
    queryFn: () =>
      apiFetch<ChannelStateSnapshot>(`/api/v1/channels/${channelId}/state`),
    enabled: !!channelId,
    // Short staleTime because the snapshot is always "as of now" — the SSE
    // stream delivers deltas thereafter, so repeated invalidations on
    // channel switch don't need to hit the network.
    staleTime: 2_000,
  });

  // Seed the chat store whenever the snapshot changes. Seeding is idempotent:
  // `rehydrateTurn` backs off if a live SSE turn already occupies the slot.
  useEffect(() => {
    if (!channelId || !query.data) return;
    const store = useChatStore.getState();
    const botName: Record<string, string> = {};
    if (bots) {
      for (const b of bots) botName[b.id] = b.name ?? b.id;
    }
    const snapshotTurnIds = new Set<string>();
    for (const turn of query.data.active_turns) {
      snapshotTurnIds.add(turn.turn_id);
      const toolCalls = turn.tool_calls.map((tc) => ({
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
        channelId,
        turn.turn_id,
        turn.bot_id,
        botName[turn.bot_id] ?? turn.bot_id,
        turn.bot_id === primaryBotId,
        toolCalls,
        skills,
      );
    }

    // Reconcile ghosts: the server snapshot is authoritative for what's
    // in-flight right now. Any local turn not in the snapshot is either a
    // just-started turn whose trace-event rows haven't landed yet (keep),
    // or a ghost left over from a lost `turn_ended` / SSE replay gap (kill).
    // The 3s grace window catches the race where SSE's `turn_started` beats
    // the first DB trace write; anything older has definitely been ignored
    // by the snapshot on purpose.
    const GHOST_GRACE_MS = 3000;
    const now = Date.now();
    const ch = store.getChannel(channelId);
    for (const [turnId, turn] of Object.entries(ch.turns)) {
      if (snapshotTurnIds.has(turnId)) continue;
      if (now - turn.startedAt < GHOST_GRACE_MS) continue;
      store.finishTurn(channelId, turnId);
    }
  }, [channelId, query.data, bots, primaryBotId]);

  return query;
}

/** Invalidate the channel-state query so the snapshot refetches and
 * reseeds. Called by useChannelEvents on replay_lapsed. */
export function invalidateChannelState(queryClient: ReturnType<typeof useQueryClient>, channelId: string) {
  queryClient.invalidateQueries({ queryKey: ["channel-state", channelId] });
}
