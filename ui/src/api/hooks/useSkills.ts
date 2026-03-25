import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface SkillItem {
  id: string;
  name: string;
  content: string;
  source_type: string;
  source_path?: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  // Workspace skill fields (only set when source_type === "workspace")
  workspace_id?: string | null;
  workspace_name?: string | null;
  mode?: string | null;
  bot_id?: string | null;
}

export function useSkills() {
  return useQuery({
    queryKey: ["admin-skills"],
    queryFn: () => apiFetch<SkillItem[]>("/api/v1/admin/skills"),
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

export function useFileSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch("/api/v1/admin/file-sync", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    },
  });
}
