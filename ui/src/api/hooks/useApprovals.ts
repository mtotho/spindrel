import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "../client";

export interface ToolApproval {
  id: string;
  session_id: string | null;
  channel_id: string | null;
  bot_id: string;
  client_id: string | null;
  correlation_id: string | null;
  tool_name: string;
  tool_type: string;
  arguments: Record<string, any>;
  policy_rule_id: string | null;
  reason: string | null;
  status: "pending" | "approved" | "denied" | "expired";
  decided_by: string | null;
  decided_at: string | null;
  dispatch_type: string | null;
  dispatch_metadata: Record<string, any> | null;
  timeout_seconds: number;
  created_at: string;
}

export interface DecideRequest {
  approved: boolean;
  decided_by?: string;
  create_rule?: {
    tool_name: string;
    conditions: Record<string, any>;
    scope?: "bot" | "global";
    priority?: number;
  };
  pin_capability?: string;
}

export interface DecideResponse {
  id: string;
  status: string;
  decided_by: string;
  decided_at: string;
  rule_created: string | null;
  capability_pinned: string | null;
}

export interface RuleSuggestion {
  label: string;
  tool_name: string;
  conditions: Record<string, any>;
  description: string;
  scope: "bot" | "global";
}

export function useApprovals(botId?: string, status?: string) {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (status) params.set("status", status);
  const qs = params.toString();
  return useQuery({
    queryKey: ["approvals", botId, status],
    queryFn: () =>
      apiFetch<ToolApproval[]>(`/api/v1/approvals${qs ? `?${qs}` : ""}`),
    refetchInterval: 5000, // Poll every 5s for pending approvals
  });
}

export function useApproval(approvalId: string | undefined) {
  return useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => apiFetch<ToolApproval>(`/api/v1/approvals/${approvalId}`),
    enabled: !!approvalId,
  });
}

export function useDecideApproval() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["approvals"] });
    qc.invalidateQueries({ queryKey: ["tool-policies"] });
    qc.invalidateQueries({ queryKey: ["bots"] });
  };
  return useMutation({
    mutationFn: async ({
      approvalId,
      data,
    }: {
      approvalId: string;
      data: DecideRequest;
    }) => {
      try {
        return await apiFetch<DecideResponse>(
          `/api/v1/approvals/${approvalId}/decide`,
          { method: "POST", body: JSON.stringify(data) },
        );
      } catch (err) {
        // 409 = approval already decided — treat as success
        if (err instanceof ApiError && err.status === 409) {
          return { id: approvalId, status: "resolved" } as unknown as DecideResponse;
        }
        throw err;
      }
    },
    retry: false,
    onSuccess: invalidate,
  });
}

export function useApprovalSuggestions(approvalId: string | undefined) {
  return useQuery({
    queryKey: ["approval-suggestions", approvalId],
    queryFn: () =>
      apiFetch<RuleSuggestion[]>(
        `/api/v1/approvals/${approvalId}/suggestions`
      ),
    enabled: !!approvalId,
  });
}

export function usePendingApprovalCount() {
  return useQuery({
    queryKey: ["approvals", undefined, "pending"],
    queryFn: () =>
      apiFetch<ToolApproval[]>("/api/v1/approvals?status=pending&limit=50"),
    refetchInterval: 30_000,
    select: (data) => data.length,
  });
}
