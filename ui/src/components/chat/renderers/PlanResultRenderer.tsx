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
    const currentRevision = sessionPlan.state?.revision ?? sessionPlan.data?.revision ?? null;
    const useCurrentDetails = currentRevision == null || fallbackPlan.revision === currentRevision;
    return {
      ...fallbackPlan,
      accepted_revision: sessionPlan.state?.accepted_revision ?? sessionPlan.data?.accepted_revision ?? fallbackPlan.accepted_revision,
      revisions: sessionPlan.data?.revisions ?? fallbackPlan.revisions,
      runtime: useCurrentDetails ? (sessionPlan.state?.runtime ?? sessionPlan.data?.runtime ?? fallbackPlan.runtime) : fallbackPlan.runtime,
      validation: useCurrentDetails ? (sessionPlan.state?.validation ?? sessionPlan.data?.validation ?? fallbackPlan.validation) : fallbackPlan.validation,
      planning_state: useCurrentDetails
        ? (sessionPlan.state?.planning_state ?? sessionPlan.data?.planning_state ?? fallbackPlan.planning_state)
        : fallbackPlan.planning_state,
      adherence: useCurrentDetails
        ? (sessionPlan.state?.adherence ?? sessionPlan.data?.adherence ?? fallbackPlan.adherence)
        : fallbackPlan.adherence,
    } satisfies SessionPlan;
  }, [fallbackPlan, sessionPlan.data, sessionPlan.state]);

  if (!plan) return null;

  const busy = sessionPlan.startPlan.isPending
    || sessionPlan.approvePlan.isPending
    || sessionPlan.exitPlan.isPending
    || sessionPlan.resumePlan.isPending
    || sessionPlan.updateStepStatus.isPending
    || sessionPlan.requestReplan.isPending
    || sessionPlan.reviewAdherence.isPending;

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
      onReplan={() => {
        const reason = window.prompt("Why does this plan need revision?");
        if (!reason?.trim()) return;
        sessionPlan.requestReplan.mutate({ reason });
      }}
      onReviewLatestOutcome={(correlationId) => sessionPlan.reviewAdherence.mutate({ correlationId })}
    />
  );
}
