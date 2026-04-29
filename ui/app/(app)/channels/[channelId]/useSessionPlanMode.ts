import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import { getAuthToken, useAuthStore } from "@/src/stores/auth";

export interface SessionPlanStep {
  id: string;
  label: string;
  status: "pending" | "in_progress" | "done" | "blocked";
  note?: string | null;
}

export interface SessionPlanArtifact {
  kind: string;
  label: string;
  ref?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SessionPlanRevision {
  revision: number;
  title: string;
  status: "draft" | "approved" | "executing" | "blocked" | "done";
  summary: string;
  path?: string | null;
  created_at?: string | null;
  is_active: boolean;
  is_accepted: boolean;
  source: "current" | "snapshot";
  changed_sections: string[];
}

export interface SessionPlanRevisionDiff {
  from_revision: number;
  to_revision: number;
  changed_sections: string[];
  diff: string;
}

export interface PlanValidationIssue {
  code: string;
  severity: "error" | "warning";
  field: string;
  message: string;
}

export interface PlanValidationResult {
  ok: boolean;
  blocking_count: number;
  warning_count: number;
  issues: PlanValidationIssue[];
}

export interface PlanRuntimeCapsule {
  schema_version: number;
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
  plan_revision?: number | null;
  accepted_revision?: number | null;
  plan_status?: "draft" | "approved" | "executing" | "blocked" | "done" | null;
  current_step_id?: string | null;
  next_step_id?: string | null;
  last_completed_step_id?: string | null;
  next_action?: string | null;
  unresolved_questions?: string[];
  blockers?: string[];
  adherence_status?: "ok" | "warning" | "blocked" | "unknown" | "planning" | null;
  semantic_status?: "ok" | "warning" | "needs_replan" | "unknown" | null;
  latest_evidence?: PlanExecutionEvidence | null;
  latest_outcome?: PlanProgressOutcome | null;
  latest_semantic_review?: PlanSemanticReview | null;
  pending_turn_outcome?: PendingTurnOutcome | null;
  replan?: {
    reason?: string;
    affected_step_ids?: string[];
    evidence?: string | null;
    from_revision?: number | null;
    created_at?: string;
  } | null;
  compaction_watermark_message_id?: string | null;
  last_updated_at?: string | null;
  last_update_reason?: string | null;
}

export interface PendingTurnOutcome {
  created_at?: string;
  reason?: string;
  turn_id?: string | null;
  correlation_id?: string | null;
  plan_revision?: number | null;
  accepted_revision?: number | null;
  step_id?: string | null;
  assistant_summary?: string | null;
}

export interface PlanningStateItem {
  text: string;
  created_at?: string;
  source?: string;
  [key: string]: unknown;
}

export interface PlanningStateCapsule {
  schema_version: number;
  decisions: PlanningStateItem[];
  open_questions: PlanningStateItem[];
  assumptions: PlanningStateItem[];
  constraints: PlanningStateItem[];
  non_goals: PlanningStateItem[];
  evidence: PlanningStateItem[];
  preference_changes: PlanningStateItem[];
  last_updated_at?: string | null;
  last_update_reason?: string | null;
}

export interface PlanExecutionEvidence {
  created_at?: string;
  plan_revision?: number | null;
  accepted_revision?: number | null;
  step_id?: string | null;
  turn_id?: string | null;
  correlation_id?: string | null;
  tool_name?: string;
  tool_kind?: string;
  status?: string;
  error?: string | null;
  tool_call_id?: string | null;
  record_id?: string | null;
  arguments?: Record<string, unknown>;
  summary?: string;
}

export interface PlanProgressOutcome {
  created_at?: string;
  outcome?: "progress" | "verification" | "step_done" | "blocked" | "no_progress";
  summary?: string;
  evidence?: string | null;
  status_note?: string | null;
  plan_revision?: number | null;
  accepted_revision?: number | null;
  step_id?: string | null;
  turn_id?: string | null;
  correlation_id?: string | null;
}

export interface PlanSemanticReview {
  created_at?: string;
  plan_revision?: number | null;
  accepted_revision?: number | null;
  step_id?: string | null;
  turn_id?: string | null;
  correlation_id?: string | null;
  outcome?: PlanProgressOutcome["outcome"] | null;
  verdict?: "supported" | "weak_support" | "unsupported" | "needs_replan" | null;
  semantic_status?: "ok" | "warning" | "needs_replan" | "unknown" | null;
  confidence?: number | null;
  reason?: string | null;
  recommended_action?: "continue" | "repeat_step" | "review_manually" | "request_replan" | null;
  deterministic_flags?: string[];
  evidence_snapshot?: Record<string, unknown> | null;
  judge_raw?: string | null;
}

export interface PlanAdherenceState {
  schema_version: number;
  status: "ok" | "warning" | "blocked" | "unknown" | "planning";
  evidence: PlanExecutionEvidence[];
  outcomes?: PlanProgressOutcome[];
  semantic_reviews?: PlanSemanticReview[];
  latest_evidence?: PlanExecutionEvidence | null;
  latest_outcome?: PlanProgressOutcome | null;
  latest_semantic_review?: PlanSemanticReview | null;
  last_transition?: string | null;
  last_updated_at?: string | null;
}

export interface SessionPlan {
  title: string;
  status: "draft" | "approved" | "executing" | "blocked" | "done";
  revision: number;
  session_id: string;
  task_slug: string;
  summary: string;
  scope: string;
  key_changes?: string[];
  interfaces?: string[];
  assumptions: string[];
  assumptions_and_defaults?: string[];
  open_questions: string[];
  steps: SessionPlanStep[];
  test_plan?: string[];
  artifacts: SessionPlanArtifact[];
  acceptance_criteria: string[];
  risks?: string[];
  outcome: string;
  path?: string | null;
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
  accepted_revision?: number | null;
  revisions?: SessionPlanRevision[];
  runtime?: PlanRuntimeCapsule | null;
  planning_state?: PlanningStateCapsule | null;
  adherence?: PlanAdherenceState | null;
  validation?: PlanValidationResult | null;
}

export interface SessionPlanState {
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
  has_plan: boolean;
  path?: string | null;
  task_slug?: string | null;
  revision?: number | null;
  accepted_revision?: number | null;
  status?: "draft" | "approved" | "executing" | "blocked" | "done" | null;
  revision_count?: number;
  planning_state?: PlanningStateCapsule | null;
  adherence?: PlanAdherenceState | null;
  runtime?: PlanRuntimeCapsule | null;
  validation?: PlanValidationResult | null;
}

const stateQueryKeyFor = (sessionId: string | undefined) => ["session-plan-state", sessionId];
const planQueryKeyFor = (sessionId: string | undefined) => ["session-plan", sessionId];

export function useSessionPlanMode(sessionId: string | undefined) {
  const queryClient = useQueryClient();
  const [staleConflict, setStaleConflict] = useState<string | null>(null);
  const lastSeqRef = useRef<number | null>(null);

  const stateQuery = useQuery({
    queryKey: stateQueryKeyFor(sessionId),
    enabled: !!sessionId,
    queryFn: async () => {
      if (!sessionId) return null;
      return apiFetch<SessionPlanState>(`/sessions/${sessionId}/plan-state`);
    },
  });

  const planQuery = useQuery({
    queryKey: planQueryKeyFor(sessionId),
    enabled: !!sessionId && !!stateQuery.data?.has_plan,
    queryFn: async () => {
      if (!sessionId) return null;
      try {
        return await apiFetch<SessionPlan>(`/sessions/${sessionId}/plan`);
      } catch (error: any) {
        const status = error?.status ?? error?.response?.status;
        if (status === 404) return null;
        throw error;
      }
    },
  });

  useEffect(() => {
    if (!sessionId) return;

    const { serverUrl } = useAuthStore.getState();
    if (!serverUrl) return;

    let retryCount = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let abortController: AbortController | null = null;

    function connect() {
      if (stopped) return;
      const token = getAuthToken();
      const since = lastSeqRef.current != null ? `?since=${lastSeqRef.current}` : "";
      abortController = new AbortController();

      fetch(`${serverUrl}/api/v1/sessions/${sessionId}/events${since}`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: "text/event-stream",
        },
        signal: abortController.signal,
      })
        .then(async (res) => {
          if (!res.ok || !res.body) {
            throw new Error(`session SSE connect failed: ${res.status}`);
          }
          retryCount = 0;

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done || stopped) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              let frame: any;
              try {
                frame = JSON.parse(line.slice(6));
              } catch {
                continue;
              }
              if (typeof frame?.seq === "number") {
                lastSeqRef.current = frame.seq;
              }
              if (frame?.kind === "replay_lapsed") {
                lastSeqRef.current = null;
                queryClient.invalidateQueries({ queryKey: stateQueryKeyFor(sessionId) });
                queryClient.invalidateQueries({ queryKey: planQueryKeyFor(sessionId) });
                continue;
              }
              if (frame?.kind !== "session_plan_updated") continue;
              const payload = frame?.payload;
              if (payload?.session_id && payload.session_id !== sessionId) continue;
              setStaleConflict(null);
              if (payload?.state) {
                queryClient.setQueryData(stateQueryKeyFor(sessionId), payload.state as SessionPlanState);
              }
              if (payload?.plan) {
                queryClient.setQueryData(planQueryKeyFor(sessionId), payload.plan as SessionPlan);
              } else {
                queryClient.setQueryData(planQueryKeyFor(sessionId), null);
              }
            }
          }

          if (!stopped) {
            retryTimer = setTimeout(connect, 1000);
          }
        })
        .catch(() => {
          if (stopped || abortController?.signal.aborted) return;
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = setTimeout(connect, delay);
        });
    }

    connect();
    return () => {
      stopped = true;
      abortController?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [queryClient, sessionId]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: stateQueryKeyFor(sessionId) });
    queryClient.invalidateQueries({ queryKey: planQueryKeyFor(sessionId) });
  };

  const capturePlanConflict = (error: any) => {
    const status = error?.status ?? error?.response?.status;
    if (status === 409) {
      setStaleConflict(error?.detail ?? error?.message ?? "The plan revision changed. Refreshing to the latest revision.");
      invalidate();
    }
  };

  const startPlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlanState>(`/sessions/${sessionId}/plan/start`, { method: "POST" });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const approvePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: stateQuery.data?.revision ?? null }),
      });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const exitPlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch(`/sessions/${sessionId}/plan/exit`, { method: "POST" });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const resumePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/resume`, { method: "POST" });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const updateStepStatus = useMutation({
    mutationFn: async ({ stepId, status, note }: { stepId: string; status: SessionPlanStep["status"]; note?: string }) => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/steps/${stepId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note, revision: stateQuery.data?.revision ?? null }),
      });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const requestReplan = useMutation({
    mutationFn: async ({ reason, affectedStepIds, evidence }: { reason: string; affectedStepIds?: string[]; evidence?: string }) => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/replan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason,
          affected_step_ids: affectedStepIds,
          evidence,
          revision: stateQuery.data?.revision ?? null,
        }),
      });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  const reviewAdherence = useMutation({
    mutationFn: async ({ correlationId }: { correlationId?: string } = {}) => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/review-adherence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ correlation_id: correlationId ?? null }),
      });
    },
    onSuccess: invalidate,
    onError: capturePlanConflict,
  });

  return {
    ...stateQuery,
    data: planQuery.data,
    mode: stateQuery.data?.mode ?? "chat",
    hasPlan: !!stateQuery.data?.has_plan,
    state: stateQuery.data ?? null,
    staleConflict,
    clearStaleConflict: () => setStaleConflict(null),
    planQuery,
    startPlan,
    approvePlan,
    exitPlan,
    resumePlan,
    updateStepStatus,
    requestReplan,
    reviewAdherence,
  };
}
