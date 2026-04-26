import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export type AttentionSeverity = "info" | "warning" | "error" | "critical";
export type AttentionStatus = "open" | "acknowledged" | "responded" | "resolved";
export type AttentionSourceType = "bot" | "system";
export type AttentionTargetKind = "channel" | "bot" | "widget" | "system";

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
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  responded_at?: string | null;
  resolved_at?: string | null;
}

interface AttentionResponse {
  items: WorkspaceAttentionItem[];
}

interface AttentionItemResponse {
  item: WorkspaceAttentionItem;
}

export const WORKSPACE_ATTENTION_KEY = ["workspace-attention"] as const;

export function useWorkspaceAttention(channelId?: string | null) {
  return useQuery({
    queryKey: channelId ? [...WORKSPACE_ATTENTION_KEY, channelId] : WORKSPACE_ATTENTION_KEY,
    queryFn: async () => {
      const params = new URLSearchParams();
      if (channelId) params.set("channel_id", channelId);
      const suffix = params.toString() ? `?${params.toString()}` : "";
      const res = await apiFetch<AttentionResponse>(`/api/v1/workspace/attention${suffix}`);
      return res.items;
    },
    refetchInterval: 15_000,
  });
}

function useAttentionAction(path: (id: string) => string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await apiFetch<AttentionItemResponse>(path(id), { method: "POST" });
      return res.item;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: WORKSPACE_ATTENTION_KEY });
    },
  });
}

export function useAcknowledgeAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/acknowledge`);
}

export function useResolveAttentionItem() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/resolve`);
}

export function useMarkAttentionResponded() {
  return useAttentionAction((id) => `/api/v1/workspace/attention/${id}/responded`);
}
