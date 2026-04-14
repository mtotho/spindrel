import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SkillItem {
  id: string;
  name: string;
  description?: string | null;
  category?: string | null;
  triggers?: string[];
  content: string;
  source_type: string;
  source_path?: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  last_surfaced_at?: string | null;
  surface_count: number;
  total_auto_injects: number;
  bot_id?: string | null;
  enrolled_bot_count: number;
}

export function useSkills(opts?: {
  source_type?: string;
  bot_id?: string;
  sort?: "name" | "recent";
  days?: number;
}) {
  const params = new URLSearchParams();
  if (opts?.source_type) params.set("source_type", opts.source_type);
  if (opts?.bot_id) params.set("bot_id", opts.bot_id);
  if (opts?.sort) params.set("sort", opts.sort);
  if (opts?.days !== undefined && opts.days > 0) params.set("days", String(opts.days));
  const qs = params.toString();
  return useQuery({
    queryKey: ["admin-skills", qs],
    queryFn: () =>
      apiFetch<SkillItem[]>(`/api/v1/admin/skills${qs ? `?${qs}` : ""}`),
  });
}

export function useSkill(skillId: string | undefined) {
  return useQuery({
    queryKey: ["admin-skill", skillId],
    queryFn: () => apiFetch<SkillItem>(`/api/v1/admin/skills/${skillId}`),
    enabled: !!skillId && skillId !== "new",
  });
}

export function useCreateSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { id: string; name: string; content: string }) =>
      apiFetch<SkillItem>("/api/v1/admin/skills", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    },
  });
}

export function useUpdateSkill(skillId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name?: string; content?: string }) =>
      apiFetch<SkillItem>(`/api/v1/admin/skills/${skillId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
      qc.invalidateQueries({ queryKey: ["admin-skill", skillId] });
    },
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiFetch(`/api/v1/admin/skills/${skillId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    },
  });
}

export interface FileSyncResult {
  ok: boolean;
  added: number;
  updated: number;
  unchanged: number;
  deleted: number;
  errors: string[];
  _diagnostics?: {
    cwd: string;
    skills_dir_resolved: string | null;
    skills_dir_exists: boolean;
    files_on_disk: { id: string; path: string; source_type: string }[];
  };
}

export function useFileSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<FileSyncResult>("/api/v1/admin/file-sync", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    },
  });
}
