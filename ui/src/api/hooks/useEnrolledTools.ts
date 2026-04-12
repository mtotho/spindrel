import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface EnrolledTool {
  tool_name: string;
  source: string;
  enrolled_at: string;
}

export function useEnrolledTools(botId?: string) {
  return useQuery({
    queryKey: ["bot-enrolled-tools", botId],
    queryFn: () =>
      apiFetch<EnrolledTool[]>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/enrolled-tools`
      ),
    enabled: !!botId,
  });
}

export function useUnenrollTool(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (toolName: string) =>
      apiFetch(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/enrolled-tools/${encodeURIComponent(toolName)}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-enrolled-tools", botId] });
    },
  });
}
