import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface EmbeddingHealth {
  healthy: boolean;
  model: string;
  litellm_base_url: string;
  error: string | null;
}

export interface FileSkillsDiag {
  files_on_disk: number;
  files_detail: Array<{ path: string; id: string; type: string }>;
  skills_in_db_total: number;
  skills_in_db_file_sourced: number;
  skill_document_chunks: number;
  knowledge_files_on_disk: number;
}

export interface WorkspaceSkillDiag {
  workspace_id: string;
  workspace_name: string;
  skills_enabled: boolean;
  document_chunks: number;
  distinct_skills: number;
}

export interface FsIndexDiag {
  bot_id: string;
  workspace_root: string;
  root_exists: boolean;
  files_on_disk: number;
  memory_files_on_disk: number;
  chunks_in_db: number;
  memory_chunks_in_db: number;
  chunks_with_embedding: number;
  chunks_with_tsv: number;
  shared_workspace_id: string | null;
  memory_scheme: string | null;
}

export interface IndexingDiagnostics {
  cwd: string;
  healthy: boolean;
  embedding_dimensions?: number;
  issues: string[];
  systems: {
    embedding: EmbeddingHealth;
    file_skills: FileSkillsDiag;
    workspace_skills: WorkspaceSkillDiag[];
    filesystem_indexing: FsIndexDiag[];
  };
}

export interface ReindexResult {
  ok: boolean;
  filesystem: Array<{
    bot_id: string;
    root: string;
    indexed?: number;
    skipped?: number;
    removed?: number;
    errors?: number;
    error?: string;
  }>;
  workspace_skills: Array<{
    workspace: string;
    total?: number;
    embedded?: number;
    unchanged?: number;
    errors?: number;
    orphans_deleted?: number;
    error?: string;
  }>;
}

// ── Disk usage ──────────────────────────────────────────────────

export interface FilesystemUsage {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  usage_percent: number;
}

export interface WorkspaceDiskEntry {
  type: "shared" | "bot";
  id: string;
  name: string;
  path: string;
  total_bytes: number;
  file_count: number;
  subdirs?: Record<string, number>;
}

export interface AttachmentDiskStats {
  total_count: number;
  with_file_data_count: number;
  total_size_bytes: number;
}

export interface DiskUsageReport {
  filesystem: FilesystemUsage;
  workspace_base_dir: string;
  workspace_total_bytes: number;
  workspaces: WorkspaceDiskEntry[];
  attachments?: AttachmentDiskStats;
}

export function useDiskUsage() {
  return useQuery({
    queryKey: ["admin-diagnostics-disk-usage"],
    queryFn: () => apiFetch<DiskUsageReport>("/api/v1/admin/diagnostics/disk-usage"),
    staleTime: 30_000,
  });
}

// ── Indexing ─────────────────────────────────────────────────────

export function useIndexingDiagnostics() {
  return useQuery({
    queryKey: ["admin-diagnostics-indexing"],
    queryFn: () => apiFetch<IndexingDiagnostics>("/api/v1/admin/diagnostics/indexing"),
  });
}

export function useReindex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ReindexResult>("/api/v1/admin/diagnostics/reindex", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-diagnostics-indexing"] });
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    },
  });
}
