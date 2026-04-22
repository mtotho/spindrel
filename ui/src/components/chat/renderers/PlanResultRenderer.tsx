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
  const plan = useMemo(() => {
    if (!fallbackPlan) return sessionPlan.data ?? null;
    return {
      ...fallbackPlan,
      accepted_revision: sessionPlan.state?.accepted_revision ?? sessionPlan.data?.accepted_revision ?? fallbackPlan.accepted_revision,
      revisions: sessionPlan.data?.revisions ?? fallbackPlan.revisions,
    } satisfies SessionPlan;
  }, [fallbackPlan, sessionPlan.data, sessionPlan.state?.accepted_revision]);

  if (!plan) return null;

  const busy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || sessionPlan.updateStepStatus.isPending;

  return (
    <SessionPlanCard
      plan={plan}
      sessionId={sessionId ?? plan.session_id}
      busy={busy}
      showPath={false}
      currentRevision={sessionPlan.state?.revision ?? sessionPlan.data?.revision ?? null}
      acceptedRevision={sessionPlan.state?.accepted_revision ?? sessionPlan.data?.accepted_revision ?? null}
      staleMessage={sessionPlan.staleConflict}
      onApprove={() => sessionPlan.approvePlan.mutate()}
      onExit={() => sessionPlan.exitPlan.mutate()}
      onStepStatus={(stepId, status) => {
        const note = status === "blocked" ? (window.prompt("Why is this step blocked?") ?? "") : undefined;
        sessionPlan.updateStepStatus.mutate({ stepId, status, note });
      }}
    />
  );
}
