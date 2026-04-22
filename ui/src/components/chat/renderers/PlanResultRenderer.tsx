import { useMemo } from "react";
import type { ToolResultEnvelope } from "@/src/types/api";
import { SessionPlanCard } from "@/app/(app)/channels/[channelId]/SessionPlanCard";
import type { SessionPlan } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";
import { useSessionPlanMode } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";

function parsePlan(envelope: ToolResultEnvelope): SessionPlan | null {
  const raw = envelope.body;
  if (raw == null) return null;
  try {
    return typeof raw === "string" ? JSON.parse(raw) as SessionPlan : raw as unknown as SessionPlan;
  } catch {
    return null;
  }
}

export function PlanResultRenderer({
  envelope,
  sessionId,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
}) {
  const sessionPlan = useSessionPlanMode(sessionId);
  const fallbackPlan = useMemo(() => parsePlan(envelope), [envelope]);
  const plan = sessionPlan.data ?? fallbackPlan;

  if (!plan) return null;

  const busy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || sessionPlan.updateStepStatus.isPending;

  return (
    <SessionPlanCard
      plan={plan}
      busy={busy}
      showPath={false}
      onApprove={() => sessionPlan.approvePlan.mutate()}
      onExit={() => sessionPlan.exitPlan.mutate()}
      onStepStatus={(stepId, status) => {
        const note = status === "blocked" ? (window.prompt("Why is this step blocked?") ?? "") : undefined;
        sessionPlan.updateStepStatus.mutate({ stepId, status, note });
      }}
    />
  );
}
