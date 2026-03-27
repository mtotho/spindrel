import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  SharedWorkspace,
  WorkspaceCreate,
  WorkspaceUpdate,
  WorkspaceFileEntry,
} from "../../types/api";

export function useWorkspaces() {
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: () => apiFetch<SharedWorkspace[]>("/api/v1/workspaces"),
  });
}

export function useWorkspace(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["workspaces", workspaceId],
    queryFn: () => apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}`),
    enabled: !!workspaceId,
  });
}

export function useCreateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: WorkspaceCreate) =>
      apiFetch<SharedWorkspace>("/api/v1/workspaces", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useUpdateWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: WorkspaceUpdate) =>
      apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
    },
  });
}

export function useDeleteWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workspaceId: string) =>
      apiFetch(`/api/v1/workspaces/${workspaceId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

// Container controls

export function useStartWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}/start`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useStopWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}/stop`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useRecreateWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}/recreate`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function usePullWorkspaceImage(workspaceId: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ success: boolean; output: string }>(
        `/api/v1/workspaces/${workspaceId}/pull`,
        { method: "POST" }
      ),
  });
}

export function useWorkspaceStatus(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["workspace-status", workspaceId],
    queryFn: () =>
      apiFetch<{ status: string }>(`/api/v1/workspaces/${workspaceId}/status`),
    enabled: !!workspaceId,
    refetchInterval: 5000,
  });
}

export function useWorkspaceLogs(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["workspace-logs", workspaceId],
    queryFn: () =>
      apiFetch<{ logs: string }>(`/api/v1/workspaces/${workspaceId}/logs`),
    enabled: !!workspaceId,
  });
}

// Bot management

export function useAddBotToWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { bot_id: string; role?: string; cwd_override?: string }) =>
      apiFetch<SharedWorkspace>(`/api/v1/workspaces/${workspaceId}/bots`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

export function useUpdateWorkspaceBot(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { bot_id: string; role?: string; cwd_override?: string }) =>
      apiFetch(`/api/v1/workspaces/${workspaceId}/bots/${data.bot_id}`, {
        method: "PUT",
        body: JSON.stringify({ role: data.role, cwd_override: data.cwd_override }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

export function useRemoveBotFromWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (botId: string) =>
      apiFetch(`/api/v1/workspaces/${workspaceId}/bots/${botId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspaces", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspaces"] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

// File browser

export function useWorkspaceFiles(
  workspaceId: string | undefined,
  path: string = "/"
) {
  return useQuery({
    queryKey: ["workspace-files", workspaceId, path],
    queryFn: () =>
      apiFetch<{ path: string; entries: WorkspaceFileEntry[] }>(
        `/api/v1/workspaces/${workspaceId}/files?path=${encodeURIComponent(path)}`
      ),
    enabled: !!workspaceId,
  });
}

// File content operations

export function useWorkspaceFileContent(
  workspaceId: string | undefined,
  path: string | null
) {
  return useQuery({
    queryKey: ["workspace-file-content", workspaceId, path],
    queryFn: () =>
      apiFetch<{ path: string; content: string; size: number }>(
        `/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(path!)}`
      ),
    enabled: !!workspaceId && !!path,
  });
}

export function useWriteWorkspaceFile(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { path: string; content: string }) =>
      apiFetch<{ path: string; size: number }>(
        `/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(data.path)}`,
        { method: "PUT", body: JSON.stringify({ content: data.content }) }
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["workspace-file-content", workspaceId, vars.path] });
      qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
    },
  });
}

export function useMkdirWorkspace(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      apiFetch<{ path: string }>(
        `/api/v1/workspaces/${workspaceId}/files/mkdir?path=${encodeURIComponent(path)}`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
    },
  });
}

export function useDeleteWorkspaceFile(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      apiFetch<{ path: string; deleted: boolean }>(
        `/api/v1/workspaces/${workspaceId}/files?path=${encodeURIComponent(path)}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
      qc.invalidateQueries({ queryKey: ["workspace-file-content", workspaceId] });
    },
  });
}

// File upload (multipart — cannot use apiFetch which sets JSON content-type)

export function useUploadWorkspaceFile(workspaceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, targetDir }: { file: File; targetDir: string }) => {
      const { useAuthStore } = await import("../../stores/auth");
      const { serverUrl } = useAuthStore.getState();
      const { getAuthToken } = await import("../../stores/auth");
      if (!serverUrl) throw new Error("Server not configured");

      const formData = new FormData();
      formData.append("file", file);
      formData.append("target_dir", targetDir);

      const token = getAuthToken();
      const res = await fetch(
        `${serverUrl}/api/v1/workspaces/${workspaceId}/files/upload`,
        {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        }
      );
      if (!res.ok) {
        const body = await res.text().catch(() => null);
        throw new Error(`Upload failed (${res.status}): ${body}`);
      }
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workspace-files", workspaceId] });
    },
  });
}

// Reindex

export function useReindexWorkspace(workspaceId: string) {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ results: Record<string, any> }>(
        `/api/v1/workspaces/${workspaceId}/reindex`,
        { method: "POST" }
      ),
  });
}
