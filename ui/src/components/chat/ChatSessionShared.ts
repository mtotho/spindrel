import { useCallback } from "react";
import { useSessionPlanMode } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";
import { useChatStore } from "@/src/stores/chat";

export function makeClientLocalId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined;
  if (cryptoObj?.randomUUID) return `web-${cryptoObj.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function formatSessionHeaderTimestamp(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatHeaderTurnMeta(stats: {
  turnsInContext: number | null;
  turnsUntilCompaction: number | null;
} | null | undefined): string[] {
  const bits: string[] = [];
  if (typeof stats?.turnsInContext === "number") {
    bits.push(`${stats.turnsInContext} turn${stats.turnsInContext === 1 ? "" : "s"} in ctx`);
  }
  if (typeof stats?.turnsUntilCompaction === "number") {
    bits.push(`${stats.turnsUntilCompaction} until compact`);
  }
  return bits;
}

export function markSessionMessageQueued(
  sessionId: string,
  clientLocalId: string,
  result: { task_id?: string; coalesced?: boolean; queued_message_count?: number },
) {
  const store = useChatStore.getState();
  const current = store.channels[sessionId]?.messages ?? [];
  const localQueuedCount = current.filter((message) => {
    const meta = (message.metadata ?? {}) as Record<string, unknown>;
    return message.role === "user" && (
      meta.client_local_id === clientLocalId ||
      meta.local_status === "queued"
    );
  }).length;
  const queuedCount = Math.max(result.queued_message_count ?? 0, localQueuedCount);
  store.setMessages(sessionId, current.map((message) => {
    const meta = (message.metadata ?? {}) as Record<string, any>;
    const isQueuedLocal =
      message.role === "user" &&
      (meta.client_local_id === clientLocalId || meta.local_status === "queued");
    if (!isQueuedLocal) return message;
    return {
      ...message,
      metadata: {
        ...meta,
        local_status: "queued",
        queued_task_id: result.task_id,
        queued_message_count: queuedCount,
        queued_coalesced: result.coalesced ?? queuedCount > 1,
      },
    };
  }));
}

export function useChatSessionPlan(sessionId: string | null | undefined) {
  const sessionPlan = useSessionPlanMode(sessionId ?? undefined);
  const planBusy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || sessionPlan.updateStepStatus.isPending;
  const handleTogglePlanMode = useCallback(() => {
    if (!sessionId) return;
    if (sessionPlan.mode !== "chat") {
      sessionPlan.exitPlan.mutate();
      return;
    }
    if (sessionPlan.hasPlan) {
      sessionPlan.resumePlan.mutate();
      return;
    }
    sessionPlan.startPlan.mutate();
  }, [sessionId, sessionPlan]);
  return { sessionPlan, planBusy, handleTogglePlanMode };
}
