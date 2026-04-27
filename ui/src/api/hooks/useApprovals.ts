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
  approval_metadata: Record<string, any> | null;
  tool_call_id: string | null;
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
  /** Harness-only: when approving, also auto-approve every subsequent tool
   *  call in the SAME turn. Reverted by the turn-finally cleanup. The backend
   *  rejects this for non-harness approvals. */
  bypass_rest_of_turn?: boolean;
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

export function usePendingApprovalCount(excludeChannelId?: string) {
  // Cross-channel count surfaces in the global ApprovalToast. SSE invalidates
  // this key on approval lifecycle events in channels the user is currently
  // viewing; the 60s fallback catches approvals landing in channels with no
  // active SSE subscription.
  return useQuery({
    queryKey: ["approvals", undefined, "pending"],
    queryFn: () =>
      apiFetch<ToolApproval[]>("/api/v1/approvals?status=pending&limit=50"),
    refetchInterval: 60_000,
    select: (data) =>
      excludeChannelId
        ? data.filter((a) => a.channel_id !== excludeChannelId).length
        : data.length,
  });
}

export type HarnessApprovalMode =
  | "bypassPermissions"
  | "acceptEdits"
  | "default"
  | "plan";

interface ApprovalModeResponse {
  mode: HarnessApprovalMode;
}

export function useSessionApprovalMode(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: ["session-approval-mode", sessionId],
    queryFn: () =>
      apiFetch<ApprovalModeResponse>(`/api/v1/sessions/${sessionId}/approval-mode`),
    enabled: !!sessionId,
  });
}

export function useSetSessionApprovalMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, mode }: { sessionId: string; mode: HarnessApprovalMode }) =>
      apiFetch<ApprovalModeResponse>(`/api/v1/sessions/${sessionId}/approval-mode`, {
        method: "POST",
        body: JSON.stringify({ mode }),
      }),
    onSuccess: (data, variables) => {
      qc.setQueryData(["session-approval-mode", variables.sessionId], data);
    },
  });
}

// ---------------------------------------------------------------------------
// Harness settings (Phase 4) — per-session model / effort / runtime knobs.
// Mirrors the approval-mode hook pair above. Settings live on
// Session.metadata.harness_settings; missing keys mean "no override".
// ---------------------------------------------------------------------------

export interface HarnessSettings {
  model: string | null;
  effort: string | null;
  runtime_settings: Record<string, unknown>;
}

export interface HarnessSettingsPatch {
  // Missing key = no change. Explicit `null` = clear that field.
  model?: string | null;
  effort?: string | null;
  runtime_settings?: Record<string, unknown> | null;
}

export function useSessionHarnessSettings(
  sessionId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["session-harness-settings", sessionId],
    queryFn: () =>
      apiFetch<HarnessSettings>(
        `/api/v1/sessions/${sessionId}/harness-settings`,
      ),
    enabled: !!sessionId,
  });
}

export function useSetSessionHarnessSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sessionId,
      patch,
    }: {
      sessionId: string;
      patch: HarnessSettingsPatch;
    }) =>
      apiFetch<HarnessSettings>(
        `/api/v1/sessions/${sessionId}/harness-settings`,
        {
          method: "POST",
          body: JSON.stringify(patch),
        },
      ),
    onSuccess: (data, variables) => {
      qc.setQueryData(["session-harness-settings", variables.sessionId], data);
    },
  });
}

export interface HarnessStatus {
  runtime: string | null;
  harness_session_id: string | null;
  model: string | null;
  effort: string | null;
  permission_mode: string | null;
  pending_hint_count: number;
  last_compacted_at: string | null;
  last_turn_at: string | null;
  usage: Record<string, unknown> | null;
  cost_usd: number | null;
  context_window_tokens: number | null;
  context_remaining_pct: number | null;
  native_compaction: Record<string, unknown> | null;
  hints: Array<Record<string, unknown>>;
  bridge_status: Record<string, unknown>;
  context_note: string;
}

export function useSessionHarnessStatus(
  sessionId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["session-harness-status", sessionId],
    queryFn: () =>
      apiFetch<HarnessStatus>(
        `/api/v1/sessions/${sessionId}/harness-status`,
      ),
    enabled: !!sessionId,
    refetchInterval: 10_000,
  });
}

export function useChannelPendingApprovals(channelId: string | undefined) {
  // No polling: the channel SSE stream (``approval_requested`` /
  // ``approval_resolved``) invalidates this key — see
  // ``useChannelEvents.handleEvent`` approval branches.
  return useQuery({
    queryKey: ["approvals", "channel", channelId],
    queryFn: () =>
      apiFetch<ToolApproval[]>(
        `/api/v1/approvals?status=pending&channel_id=${channelId}&limit=50`,
      ),
    enabled: !!channelId,
  });
}
