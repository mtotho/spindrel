import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";

export interface SessionPlanStep {
  id: string;
  label: string;
  status: "pending" | "in_progress" | "done" | "blocked";
  note?: string | null;
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
  acceptance_criteria: string[];
  outcome: string;
  path?: string | null;
  mode: "chat" | "planning" | "executing" | "blocked" | "done";
}

const queryKeyFor = (sessionId: string | undefined) => ["session-plan", sessionId];

export function useSessionPlanMode(sessionId: string | undefined) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeyFor(sessionId),
    enabled: !!sessionId,
    refetchInterval: (q) => {
      const plan = q.state.data;
      return plan && plan.mode !== "chat" ? 3000 : false;
    },
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

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeyFor(sessionId) });

  const startPlan = useMutation({
    mutationFn: async (title: string) => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plans`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    },
    onSuccess: invalidate,
  });

  const approvePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/approve`, {
        method: "POST",
      });
    },
    onSuccess: invalidate,
  });

  const exitPlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch(`/sessions/${sessionId}/plan/exit`, {
        method: "POST",
      });
    },
    onSuccess: invalidate,
  });

  const resumePlan = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing session id");
      return apiFetch<SessionPlan>(`/sessions/${sessionId}/plan/resume`, {
        method: "POST",
      });
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
    ...query,
    startPlan,
    approvePlan,
    exitPlan,
    resumePlan,
    updateStepStatus,
  };
}
