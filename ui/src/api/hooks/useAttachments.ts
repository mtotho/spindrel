import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AttachmentAdmin {
  id: string;
  message_id: string | null;
  channel_id: string | null;
  channel_name: string | null;
  type: string;
  url: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  has_file_data: boolean;
  posted_by: string | null;
  source_integration: string;
  description: string | null;
  created_at: string;
}

interface AttachmentListResponse {
  attachments: AttachmentAdmin[];
  total: number;
}

export interface AttachmentGlobalStats {
  total_count: number;
  with_file_data_count: number;
  total_size_bytes: number;
  by_type: Record<string, number>;
  by_channel: Array<{
    channel_id: string;
    channel_name: string | null;
    count: number;
    size_bytes: number;
  }>;
}

export interface AttachmentStats {
  channel_id: string;
  total_count: number;
  with_file_data_count: number;
  total_size_bytes: number;
  oldest_created_at: string | null;
  effective_config: {
    retention_days: number | null;
    max_size_bytes: number | null;
    types_allowed: string[] | null;
  };
}

interface AttachmentSimple {
  id: string;
  message_id: string | null;
  channel_id: string | null;
  type: string;
  url: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  posted_by: string | null;
  source_integration: string;
  description: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Admin hooks
// ---------------------------------------------------------------------------

export function useAdminAttachments(opts: {
  channelId?: string;
  type?: string;
  limit?: number;
  offset?: number;
}) {
  const params = new URLSearchParams();
  if (opts.channelId) params.set("channel_id", opts.channelId);
  if (opts.type) params.set("type", opts.type);
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();

  return useQuery({
    queryKey: ["admin-attachments", opts],
    queryFn: () =>
      apiFetch<AttachmentListResponse>(
        `/api/v1/admin/attachments${qs ? `?${qs}` : ""}`
      ),
  });
}

export function useAttachmentGlobalStats() {
  return useQuery({
    queryKey: ["admin-attachment-stats"],
    queryFn: () =>
      apiFetch<AttachmentGlobalStats>("/api/v1/admin/attachments/stats"),
    staleTime: 30_000,
  });
}

export function useDeleteAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/attachments/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-attachments"] });
      qc.invalidateQueries({ queryKey: ["admin-attachment-stats"] });
      qc.invalidateQueries({ queryKey: ["channel-attachment-stats"] });
      qc.invalidateQueries({ queryKey: ["channel-attachments"] });
    },
  });
}

export function usePurgeAttachments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      before_date: string;
      channel_id?: string;
      type?: string;
      purge_file_data_only?: boolean;
    }) =>
      apiFetch<{ purged_count: number }>("/api/v1/admin/attachments/purge", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-attachments"] });
      qc.invalidateQueries({ queryKey: ["admin-attachment-stats"] });
      qc.invalidateQueries({ queryKey: ["channel-attachment-stats"] });
      qc.invalidateQueries({ queryKey: ["channel-attachments"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Channel-level hooks
// ---------------------------------------------------------------------------

export function useChannelAttachments(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-attachments", channelId],
    queryFn: () =>
      apiFetch<AttachmentSimple[]>(
        `/api/v1/attachments?channel_id=${channelId}&limit=100`
      ),
    enabled: !!channelId,
  });
}

export function useChannelAttachmentStats(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channel-attachment-stats", channelId],
    queryFn: () =>
      apiFetch<AttachmentStats>(
        `/api/v1/channels/${channelId}/attachment-stats`
      ),
    enabled: !!channelId,
    staleTime: 30_000,
  });
}

export function useUploadAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      file,
      channelId,
    }: {
      file: File;
      channelId: string;
    }) => {
      const { useAuthStore } = await import("../../stores/auth");
      const { serverUrl } = useAuthStore.getState();
      const { getAuthToken } = await import("../../stores/auth");
      if (!serverUrl) throw new Error("Server not configured");

      const formData = new FormData();
      formData.append("file", file);
      formData.append("channel_id", channelId);

      const token = getAuthToken();
      const res = await fetch(`${serverUrl}/api/v1/attachments/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) {
        const body = await res.text().catch(() => null);
        throw new Error(`Upload failed (${res.status}): ${body}`);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-attachments"] });
      qc.invalidateQueries({ queryKey: ["channel-attachment-stats"] });
      qc.invalidateQueries({ queryKey: ["admin-attachments"] });
      qc.invalidateQueries({ queryKey: ["admin-attachment-stats"] });
    },
  });
}
