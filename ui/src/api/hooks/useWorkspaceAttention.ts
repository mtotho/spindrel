import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { ExecutionReceipt } from "./useAgentCapabilities";

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

export interface AttentionBriefAction {
  type?: "open_item" | "copy_prompt" | string;
  item_id?: string | null;
  prompt?: string | null;
}

export interface AttentionBriefCard {
  id: string;
  kind?: string;
  title: string;
  summary: string;
  severity?: AttentionSeverity | string | null;
  target_label?: string | null;
  item_ids: string[];
  action_label?: string | null;
  action?: AttentionBriefAction | null;
}

export interface AttentionFixPack {
  id: string;
  title: string;
  summary: string;
  count: number;
  severity?: AttentionSeverity | string | null;
  target_summary?: string | null;
  item_ids: string[];
  prompt: string;
  action_label?: string | null;
  action?: AttentionBriefAction | null;
}

export interface AgentReadinessAutofixItem {
  receipt_id: string;
  bot_id?: string | null;
  channel_id?: string | null;
  session_id?: string | null;
  action_id?: string | null;
  finding_code?: string | null;
  summary: string;
  requested_by?: string | null;
  requested_at?: string | null;
  rationale?: string | null;
  requester_missing_actor_scopes?: string[];
  receipt: ExecutionReceipt;
}

export interface AttentionBriefResponse {
  generated_at: string;
  summary: {
    autofix: number;
    blockers: number;
    fix_packs: number;
    decisions: number;
    quiet: number;
    running: number;
    cleared: number;
    total: number;
  };
  next_action: {
    kind: string;
    title: string;
    description: string;
    action_label?: string | null;
    item_id?: string | null;
    fix_pack_id?: string | null;
    receipt_id?: string | null;
    action_id?: string | null;
  };
  blockers: AttentionBriefCard[];
  fix_packs: AttentionFixPack[];
  decisions: AttentionBriefCard[];
  autofix_queue: AgentReadinessAutofixItem[];
  quiet_digest: {
    count: number;
    groups: Array<{ label: string; count: number }>;
  };
  running: Array<Record<string, unknown>>;
  cleared: Array<Record<string, unknown>>;
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

export interface IssueWorkPack {
  id: string;
  title: string;
  summary: string;
  category: string;
  confidence: "low" | "medium" | "high" | string;
  status: "proposed" | "launched" | "dismissed" | "needs_info" | string;
  source_item_ids: string[];
  launch_prompt: string;
  triage_task_id?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  launched_task_id?: string | null;
  launched_task_status?: string | null;
  source_items?: Array<{
    id: string;
    title: string;
    message: string;
    severity: string;
    status: string;
    channel_id?: string | null;
    channel_name?: string | null;
    evidence?: Record<string, unknown>;
  }>;
  triage_receipt_id?: string | null;
  triage_receipt?: {
    id?: string;
    source?: string;
    summary?: string | null;
    grouping_rationale?: string | null;
    launch_readiness?: string | null;
    follow_up_questions?: string[];
    excluded_items?: string[];
    created_at?: string | null;
    bot_id?: string | null;
    session_id?: string | null;
    task_id?: string | null;
  } | null;
  latest_review_action?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface IssueWorkPackUpdateInput {
  work_pack_id: string;
  title?: string;
  summary?: string;
  category?: string;
  confidence?: string;
  source_item_ids?: string[];
  launch_prompt?: string;
  project_id?: string | null;
  channel_id?: string | null;
}

export interface IssueWorkPackBatchLaunchInput {
  work_pack_ids: string[];
  project_id: string;
  channel_id: string;
  note?: string | null;
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
export const WORKSPACE_ATTENTION_BRIEF_KEY = ["workspace-attention-brief"] as const;
export const ATTENTION_TRIAGE_RUNS_KEY = ["workspace-attention-triage-runs"] as const;
export const ISSUE_WORK_PACKS_KEY = ["workspace-issue-work-packs"] as const;

export function isActiveAttentionItem(item: WorkspaceAttentionItem): boolean {
  return item.status !== "resolved" && item.status !== "acknowledged";
}

export function getOperatorTriage(item: WorkspaceAttentionItem): OperatorTriageState | null {
  const triage = item.evidence?.operator_triage;
  return triage && typeof triage === "object" ? triage as OperatorTriageState : null;
}

const BENIGN_TOOL_ERROR_KINDS = new Set([
  "validation",
  "not_found",
  "forbidden",
  "approval_required",
  "config_missing",
  "conflict",
]);

const RETRYABLE_TOOL_ERROR_KINDS = new Set(["rate_limited", "timeout", "unavailable"]);

export interface ToolErrorReviewSignal {
  label: string;
  tone: "muted" | "warning" | "danger";
  nextAction: string | null;
  errorCode: string | null;
  errorKind: string | null;
  retryable: boolean;
}

export function getToolErrorReviewSignal(item: WorkspaceAttentionItem): ToolErrorReviewSignal | null {
  const evidence = item.evidence ?? {};
  if (evidence.kind !== "tool_call") return null;
  const classification = typeof evidence.classification === "string" ? evidence.classification : "";
  const errorKind = typeof evidence.error_kind === "string" ? evidence.error_kind : null;
  const errorCode = typeof evidence.error_code === "string" ? evidence.error_code : null;
  const retryable = evidence.retryable === true || (errorKind ? RETRYABLE_TOOL_ERROR_KINDS.has(errorKind) : false);
  const fallback = typeof evidence.fallback === "string" && evidence.fallback.trim() ? evidence.fallback.trim() : null;

  if (retryable || classification === "retryable_contract") {
    return { label: "Retryable", tone: "warning", nextAction: fallback, errorCode, errorKind, retryable: true };
  }
  if (classification === "repeated_benign_contract") {
    return { label: "Repeated benign", tone: "warning", nextAction: fallback, errorCode, errorKind, retryable: false };
  }
  if (errorKind === "internal" || classification === "platform_contract" || classification === "severe") {
    return { label: "Platform bug", tone: "danger", nextAction: fallback, errorCode, errorKind, retryable: false };
  }
  if (errorKind && BENIGN_TOOL_ERROR_KINDS.has(errorKind)) {
    return { label: "Benign setup", tone: "muted", nextAction: fallback, errorCode, errorKind, retryable: false };
  }
  return { label: "Tool failure", tone: "danger", nextAction: fallback, errorCode, errorKind, retryable: false };
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

export function useWorkspaceAttentionBrief(
  options: { enabled?: boolean; channelId?: string | null; refetchInterval?: number | false } = {},
) {
  const enabled = options.enabled ?? true;
  const channelId = options.channelId ?? null;
  return useQuery({
    queryKey: channelId ? [...WORKSPACE_ATTENTION_BRIEF_KEY, channelId] : WORKSPACE_ATTENTION_BRIEF_KEY,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (channelId) params.set("channel_id", channelId);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      return apiFetch<AttentionBriefResponse>(`/api/v1/workspace/attention/brief${suffix}`);
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
    },
  });
}

export function useStartIssueTriageRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: AttentionTriageRunInput = {}) =>
      apiFetch<AttentionTriageRunResponse>("/api/v1/workspace/attention/issue-triage-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "all_active", ...body }),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
      qc.invalidateQueries({ queryKey: ATTENTION_TRIAGE_RUNS_KEY });
      qc.invalidateQueries({ queryKey: ISSUE_WORK_PACKS_KEY });
    },
  });
}

export function useIssueWorkPacks() {
  return useQuery({
    queryKey: ISSUE_WORK_PACKS_KEY,
    queryFn: async () => {
      const res = await apiFetch<{ work_packs: IssueWorkPack[] }>("/api/v1/workspace/attention/issue-work-packs");
      return res.work_packs;
    },
    refetchInterval: 15_000,
  });
}

function invalidateIssueWorkPackQueries(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ISSUE_WORK_PACKS_KEY });
  qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
  qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
}

export function useUpdateIssueWorkPack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ work_pack_id, ...body }: IssueWorkPackUpdateInput) =>
      apiFetch<{ work_pack: IssueWorkPack }>(`/api/v1/workspace/attention/issue-work-packs/${work_pack_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSettled: () => invalidateIssueWorkPackQueries(qc),
  });
}

export function useIssueWorkPackAction(action: "dismiss" | "needs-info" | "reopen") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { work_pack_id: string; note?: string | null }) =>
      apiFetch<{ work_pack: IssueWorkPack }>(`/api/v1/workspace/attention/issue-work-packs/${body.work_pack_id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: body.note ?? null }),
      }),
    onSettled: () => invalidateIssueWorkPackQueries(qc),
  });
}

export function useLaunchIssueWorkPackProjectRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: { work_pack_id: string; project_id: string; channel_id: string }) =>
      apiFetch<{ work_pack: IssueWorkPack; run: unknown }>(`/api/v1/workspace/attention/issue-work-packs/${body.work_pack_id}/launch-project-run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: body.project_id, channel_id: body.channel_id }),
      }),
    onSettled: () => {
      invalidateIssueWorkPackQueries(qc);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useBatchLaunchIssueWorkPacksProjectRuns() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: IssueWorkPackBatchLaunchInput) =>
      apiFetch<{ launch_batch_id: string; count: number; work_packs: IssueWorkPack[]; runs: unknown[] }>("/api/v1/workspace/attention/issue-work-packs/batch-launch-project-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      invalidateIssueWorkPackQueries(qc);
      qc.invalidateQueries({ queryKey: ["projects"] });
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
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_BRIEF_KEY });
    },
  });
}
