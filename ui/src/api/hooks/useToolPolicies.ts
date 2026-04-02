import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ToolPolicyRule {
  id: string;
  bot_id: string | null;
  tool_name: string;
  action: "allow" | "deny" | "require_approval";
  conditions: Record<string, any>;
  priority: number;
  approval_timeout: number;
  reason: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ToolPolicyCreatePayload {
  bot_id?: string | null;
  tool_name: string;
  action: string;
  conditions?: Record<string, any>;
  priority?: number;
  approval_timeout?: number;
  reason?: string | null;
  enabled?: boolean;
}

export interface ToolPolicyUpdatePayload {
  bot_id?: string | null;
  tool_name?: string;
  action?: string;
  conditions?: Record<string, any>;
  priority?: number;
  approval_timeout?: number;
  reason?: string | null;
  enabled?: boolean;
}

export interface PolicyTestRequest {
  bot_id: string;
  tool_name: string;
  arguments?: Record<string, any>;
}

export interface PolicyTestResponse {
  action: string;
  rule_id: string | null;
  reason: string | null;
  timeout: number;
}

export function useToolPolicies(botId?: string, toolName?: string) {
  const params = new URLSearchParams();
  if (botId) params.set("bot_id", botId);
  if (toolName) params.set("tool_name", toolName);
  const qs = params.toString();
  return useQuery({
    queryKey: ["tool-policies", botId, toolName],
    queryFn: () =>
      apiFetch<ToolPolicyRule[]>(`/api/v1/tool-policies${qs ? `?${qs}` : ""}`),
  });
}

export function useToolPolicy(ruleId: string | undefined) {
  return useQuery({
    queryKey: ["tool-policy", ruleId],
    queryFn: () => apiFetch<ToolPolicyRule>(`/api/v1/tool-policies/${ruleId}`),
    enabled: false, // No single-get endpoint; we filter from list
  });
}

export function useCreateToolPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ToolPolicyCreatePayload) =>
      apiFetch<ToolPolicyRule>("/api/v1/tool-policies", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tool-policies"] });
    },
  });
}

export function useUpdateToolPolicy(ruleId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ToolPolicyUpdatePayload) =>
      apiFetch<ToolPolicyRule>(`/api/v1/tool-policies/${ruleId}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tool-policies"] });
    },
  });
}

export function useDeleteToolPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) =>
      apiFetch(`/api/v1/tool-policies/${ruleId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tool-policies"] });
    },
  });
}

export function useTestToolPolicy() {
  return useMutation({
    mutationFn: (data: PolicyTestRequest) =>
      apiFetch<PolicyTestResponse>("/api/v1/tool-policies/test", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}

// --- Policy settings (default action, enabled) ---

export interface PolicySettings {
  default_action: "allow" | "deny" | "require_approval";
  enabled: boolean;
}

export function usePolicySettings() {
  return useQuery({
    queryKey: ["tool-policy-settings"],
    queryFn: () => apiFetch<PolicySettings>("/api/v1/tool-policies/settings"),
  });
}

export function useUpdatePolicySettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<PolicySettings>) =>
      apiFetch<PolicySettings>("/api/v1/tool-policies/settings", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tool-policy-settings"] });
    },
  });
}
