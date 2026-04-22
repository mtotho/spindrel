import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";

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

export interface SessionPlan {
  title: string;
  status: "draft" | "approved" | "executing" | "blocked" | "done";
  revision: number;
  session_id: string;
  task_slug: string;
  summary: string;
  scope: string;
  assumptions: string[];
  open_questions: string[];
  steps: SessionPlanStep[];
  artifacts: SessionPlanArtifact[];
  acceptance_criteria: string[];
  outcome: string;
  path?: string | null;
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
}

export interface SessionPlanState {
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
  has_plan: boolean;
  path?: string | null;
  task_slug?: string | null;
  revision?: number | null;
  accepted_revision?: number | null;
  status?: "draft" | "approved" | "executing" | "blocked" | "done" | null;
}

const stateQueryKeyFor = (sessionId: string | undefined) => ["session-plan-state", sessionId];
const planQueryKeyFor = (sessionId: string | undefined) => ["session-plan", sessionId];

export function useSessionPlanMode(sessionId: string | undefined) {
  const queryClient = useQueryClient();

  const stateQuery = useQuery({
    queryKey: stateQueryKeyFor(sessionId),
    enabled: !!sessionId,
    refetchInterval: (q) => {
      const state = q.state.data;
      return state && state.mode !== "chat" ? 3000 : false;
    },
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

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: stateQueryKeyFor(sessionId) });
    queryClient.invalidateQueries({ queryKey: planQueryKeyFor(sessionId) });
  };

  const startPlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlanState>(`/sessions/${sessionId}/plan/start`, { method: "POST" });
    },
    onSuccess: invalidate,
  });

  const approvePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/approve`, { method: "POST" });
    },
    onSuccess: invalidate,
  });

  const exitPlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch(`/sessions/${sessionId}/plan/exit`, { method: "POST" });
    },
    onSuccess: invalidate,
  });

  const resumePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/resume`, { method: "POST" });
    },
    onSuccess: invalidate,
  });

  const updateStepStatus = useMutation({
    mutationFn: async ({ stepId, status, note }: { stepId: string; status: SessionPlanStep["status"]; note?: string }) => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/steps/${stepId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note }),
      });
    },
    onSuccess: invalidate,
  });

  return {
    ...stateQuery,
    data: planQuery.data,
    mode: stateQuery.data?.mode ?? "chat",
    hasPlan: !!stateQuery.data?.has_plan,
    state: stateQuery.data ?? null,
    planQuery,
    startPlan,
    approvePlan,
    exitPlan,
    resumePlan,
    updateStepStatus,
  };
}
