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

interface BulkAcknowledgeAttentionResponse {
  count: number;
  item_ids: string[];
  items: WorkspaceAttentionItem[];
}

export const WORKSPACE_ATTENTION_KEY = ["workspace-attention"] as const;

export function isActiveAttentionItem(item: WorkspaceAttentionItem): boolean {
  return item.status !== "resolved" && item.status !== "acknowledged";
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
  options: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  const enabled = options.enabled ?? true;
  return useQuery({
    queryKey: channelId ? [...WORKSPACE_ATTENTION_KEY, channelId] : WORKSPACE_ATTENTION_KEY,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (channelId) params.set("channel_id", channelId);
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
    },
  });
}

export function useUnassignAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/unassign`);
}
