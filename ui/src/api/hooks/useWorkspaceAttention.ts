import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type AttentionSeverity = "info" | "warning" | "error" | "critical";
export type AttentionStatus = "open" | "acknowledged" | "responded" | "resolved";
export type AttentionSourceType = "bot" | "system" | "user";
export type AttentionTargetKind = "channel" | "bot" | "widget" | "system";
export type AttentionAssignmentMode = "next_heartbeat" | "run_now";
export type AttentionAssignmentStatus = "assigned" | "running" | "reported" | "cancelled";

export interface WorkspaceAttentionItem {
  id: string;
  source_type: AttentionSourceType;
  source_id: string;
  channel_id: string | null;
  channel_name?: string | null;
  target_kind: AttentionTargetKind;
  target_id: string;
  target_node_id?: string | null;
  dedupe_key: string;
  severity: AttentionSeverity;
  title: string;
  message: string;
  next_steps: string[];
  requires_response: boolean;
  status: AttentionStatus;
  occurrence_count: number;
  evidence: Record<string, unknown>;
  latest_correlation_id?: string | null;
  response_message_id?: string | null;
  assigned_bot_id?: string | null;
  assignment_mode?: AttentionAssignmentMode | null;
  assignment_status?: AttentionAssignmentStatus | null;
  assignment_instructions?: string | null;
  assigned_by?: string | null;
  assigned_at?: string | null;
  assignment_task_id?: string | null;
  assignment_report?: string | null;
  assignment_reported_by?: string | null;
  assignment_reported_at?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  responded_at?: string | null;
  resolved_at?: string | null;
  queue_state?: {
    blocked?: boolean;
    blocked_reason?: string | null;
    next_run_at?: string | null;
    heartbeat_channel_id?: string | null;
  };
}

export interface OperatorTriageState {
  state?: "running" | "queued" | "processed" | "ready_for_review" | "failed" | string;
  task_id?: string | null;
  session_id?: string | null;
  parent_channel_id?: string | null;
  operator_bot_id?: string | null;
  classification?: string | null;
  confidence?: "low" | "medium" | "high" | string | null;
  summary?: string | null;
  suggested_action?: string | null;
  route?: string | null;
  review_required?: boolean | null;
  review?: {
    verdict?: string | null;
    note?: string | null;
    route?: string | null;
    reviewed_at?: string | null;
    reviewed_by?: string | null;
  } | null;
}

interface AttentionResponse {
  items: WorkspaceAttentionItem[];
}

interface AttentionItemResponse {
  item: WorkspaceAttentionItem;
}

export interface CreateAttentionInput {
  channel_id?: string | null;
  target_kind: AttentionTargetKind;
  target_id?: string | null;
  title: string;
  message: string;
  severity: AttentionSeverity;
  requires_response: boolean;
  next_steps?: string[];
}

export interface AssignAttentionInput {
  itemId: string;
  bot_id: string;
  mode: AttentionAssignmentMode;
  instructions?: string | null;
}

export interface BulkAcknowledgeAttentionInput {
  scope: "target" | "workspace_visible";
  target_kind?: AttentionTargetKind | null;
  target_id?: string | null;
  channel_id?: string | null;
}

export interface AttentionTriageRunResponse {
  task_id: string;
  session_id: string | null;
  parent_channel_id: string | null;
  bot_id: string;
  status?: "queued" | "running" | "complete" | "failed" | string | null;
  task_status?: string | null;
  item_count: number;
  counts?: {
    total: number;
    running: number;
    processed: number;
    ready_for_review: number;
    failed: number;
    unreported: number;
  };
  items?: WorkspaceAttentionItem[];
  model_override?: string | null;
  model_provider_id_override?: string | null;
  effective_model?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
}

export interface AttentionTriageRunInput {
  model_override?: string | null;
  model_provider_id_override?: string | null;
}

export interface AttentionTriageFeedbackInput {
  itemId: string;
  verdict: "confirmed" | "wrong" | "rerouted";
  note?: string | null;
  route?: string | null;
}

interface BulkAcknowledgeAttentionResponse {
  count: number;
  item_ids: string[];
  items: WorkspaceAttentionItem[];
}

export const WORKSPACE_ATTENTION_KEY = ["workspace-attention"] as const;
export const ATTENTION_TRIAGE_RUNS_KEY = ["workspace-attention-triage-runs"] as const;

export function isActiveAttentionItem(item: WorkspaceAttentionItem): boolean {
  return item.status !== "resolved" && item.status !== "acknowledged";
}

export function getOperatorTriage(item: WorkspaceAttentionItem): OperatorTriageState | null {
  const triage = item.evidence?.operator_triage;
  return triage && typeof triage === "object" ? triage as OperatorTriageState : null;
}

export function isOperatorTriageRunning(item: WorkspaceAttentionItem): boolean {
  const triage = getOperatorTriage(item);
  return triage?.state === "running" || triage?.state === "queued";
}

export function isOperatorTriageReadyForReview(item: WorkspaceAttentionItem): boolean {
  const triage = getOperatorTriage(item);
  return triage?.state === "ready_for_review" || triage?.review_required === true;
}

export function isOperatorTriageProcessed(item: WorkspaceAttentionItem): boolean {
  const triage = getOperatorTriage(item);
  return triage?.state === "processed";
}

export function reconcileAttentionItems(
  items: WorkspaceAttentionItem[] | undefined,
  updated: WorkspaceAttentionItem,
): WorkspaceAttentionItem[] | undefined {
  if (!items) return items;
  if (!isActiveAttentionItem(updated)) {
    return items.filter((item) => item.id !== updated.id);
  }
  let found = false;
  const next = items.map((item) => {
    if (item.id !== updated.id) return item;
    found = true;
    return updated;
  });
  return found ? next : items;
}

export function useWorkspaceAttention(
  channelId?: string | null,
  options: { enabled?: boolean; refetchInterval?: number | false; includeResolved?: boolean } = {},
) {
  const enabled = options.enabled ?? true;
  const includeResolved = options.includeResolved ?? false;
  return useQuery({
    queryKey: channelId
      ? [...WORKSPACE_ATTENTION_KEY, channelId, { includeResolved }]
      : [...WORKSPACE_ATTENTION_KEY, { includeResolved }],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (channelId) params.set("channel_id", channelId);
      if (includeResolved) params.set("include_resolved", "true");
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const res = await apiFetch<AttentionResponse>(`/api/v1/workspace/attention${suffix}`);
      return res.items;
    },
    enabled,
    refetchInterval: enabled ? options.refetchInterval ?? 15_000 : false,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

function useAttentionAction(path: (id: string) => string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await apiFetch<AttentionItemResponse>(path(id), { method: "POST" });
      return res.item;
    },
    onSuccess: (item) => {
      qc.setQueriesData<WorkspaceAttentionItem[]>(
        { queryKey: WORKSPACE_ATTENTION_KEY },
        (items) => reconcileAttentionItems(items, item),
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useAcknowledgeAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/acknowledge`);
}

export function useBulkAcknowledgeAttentionItems() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: BulkAcknowledgeAttentionInput) => {
      const res = await apiFetch<BulkAcknowledgeAttentionResponse>("/api/v1/workspace/attention/acknowledge-bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res;
    },
    onSuccess: (res) => {
      const ids = new Set(res.item_ids);
      qc.setQueriesData<WorkspaceAttentionItem[]>(
        { queryKey: WORKSPACE_ATTENTION_KEY },
        (items) => items ? items.filter((item) => !ids.has(item.id)) : items,
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useResolveAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/resolve`);
}

export function useMarkAttentionResponded() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/responded`);
}

export function useCreateAttentionItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateAttentionInput) => {
      const res = await apiFetch<AttentionItemResponse>("/api/v1/workspace/attention", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSuccess: (item) => {
      qc.setQueriesData<WorkspaceAttentionItem[]>(
        { queryKey: WORKSPACE_ATTENTION_KEY },
        (items) => items ? [item, ...items] : items,
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useAssignAttentionItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ itemId, ...body }: AssignAttentionInput) => {
      const res = await apiFetch<AttentionItemResponse>(`/api/v1/workspace/attention/${itemId}/assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSuccess: (item) => {
      qc.setQueriesData<WorkspaceAttentionItem[]>(
        { queryKey: WORKSPACE_ATTENTION_KEY },
        (items) => reconcileAttentionItems(items, item),
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useUnassignAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/unassign`);
}

export function useStartAttentionTriageRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AttentionTriageRunInput = {}) => {
      const res = await apiFetch<AttentionTriageRunResponse>("/api/v1/workspace/attention/triage-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "all_active", ...body }),
      });
      return res;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useAttentionTriageRuns(options: { enabled?: boolean; limit?: number; refetchInterval?: number | false } = {}) {
  const enabled = options.enabled ?? true;
  const limit = options.limit ?? 20;
  return useQuery({
    queryKey: [...ATTENTION_TRIAGE_RUNS_KEY, { limit }],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      const res = await apiFetch<{ runs: AttentionTriageRunResponse[] }>(`/api/v1/workspace/attention/triage-runs?${params.toString()}`);
      return res.runs;
    },
    enabled,
    refetchInterval: enabled ? options.refetchInterval ?? 10_000 : false,
    staleTime: 5_000,
    refetchOnWindowFocus: false,
  });
}

export function useSubmitAttentionTriageFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ itemId, ...body }: AttentionTriageFeedbackInput) => {
      const res = await apiFetch<AttentionItemResponse>(`/api/v1/workspace/attention/${itemId}/triage-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return res.item;
    },
    onSuccess: (item) => {
      qc.setQueriesData<WorkspaceAttentionItem[]>(
        { queryKey: WORKSPACE_ATTENTION_KEY },
        (items) => reconcileAttentionItems(items, item),
      );
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
    },
  });
}
