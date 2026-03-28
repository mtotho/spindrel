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
