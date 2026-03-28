import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

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
    priority?: number;
  };
}

export interface DecideResponse {
  id: string;
  status: string;
  decided_by: string;
  decided_at: string;
  rule_created: string | null;
}

export interface RuleSuggestion {
  label: string;
  tool_name: string;
  conditions: Record<string, any>;
  description: string;
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
  return useMutation({
    mutationFn: ({
      approvalId,
      data,
    }: {
      approvalId: string;
      data: DecideRequest;
    }) =>
      apiFetch<DecideResponse>(`/api/v1/approvals/${approvalId}/decide`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["approvals"] });
      qc.invalidateQueries({ queryKey: ["tool-policies"] });
    },
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
