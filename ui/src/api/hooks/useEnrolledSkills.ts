import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface EnrolledSkill {
  skill_id: string;
  name: string;
  description: string | null;
  source: string;
  enrolled_at: string;
  surface_count: number;
  last_surfaced_at: string | null;
}

export function useEnrolledSkills(botId?: string) {
  return useQuery({
    queryKey: ["bot-enrolled-skills", botId],
    queryFn: () =>
      apiFetch<EnrolledSkill[]>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/enrolled-skills`
      ),
    enabled: !!botId,
  });
}

export function useEnrollSkill(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ skillId, source }: { skillId: string; source?: string }) =>
      apiFetch<{ status: string; skill_id: string; inserted: boolean }>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/enrolled-skills`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill_id: skillId, source: source ?? "manual" }),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-enrolled-skills", botId] });
    },
  });
}

export function useUnenrollSkill(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (skillId: string) =>
      apiFetch(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/enrolled-skills/${encodeURIComponent(skillId)}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-enrolled-skills", botId] });
    },
  });
}
