import { useCallback } from "react";
import { useSessionPlanMode } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";

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
