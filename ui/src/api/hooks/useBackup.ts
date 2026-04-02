import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface BackupConfig {
  rclone_remote: string;
  local_keep: number;
  aws_region: string;
  backup_dir: string;
}

export interface BackupFile {
  name: string;
  size_bytes: number;
  modified_at: string;
}

interface BackupHistoryResponse {
  backup_dir: string;
  files: BackupFile[];
}

export function useBackupConfig() {
  return useQuery({
    queryKey: ["backup-config"],
    queryFn: () =>
      apiFetch<BackupConfig>("/api/v1/admin/operations/backup/config"),
  });
}

export function useUpdateBackupConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (config: Partial<BackupConfig>) =>
      apiFetch<BackupConfig>("/api/v1/admin/operations/backup/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["backup-config"] });
    },
  });
}

export function useTriggerBackup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ operation_id: string; status: string }>(
        "/api/v1/admin/operations/backup",
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-diagnostics-operations"] });
    },
  });
}

export function useBackupHistory() {
  return useQuery({
    queryKey: ["backup-history"],
    queryFn: () =>
      apiFetch<BackupHistoryResponse>(
        "/api/v1/admin/operations/backup/history"
      ),
  });
}
