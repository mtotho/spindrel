import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface MemoryItem {
  id: string;
  session_id?: string | null;
  client_id: string;
  bot_id: string;
  content: string;
  message_count?: number | null;
  correlation_id?: string | null;
  created_at: string;
}

export function useBotMemories(botId: string | undefined) {
  return useQuery({
    queryKey: ["bot-memories", botId],
    queryFn: async () => {
      const res = await apiFetch<{ memories: MemoryItem[] }>(
        `/api/v1/admin/bots/${botId}/memories?limit=50`
      );
      return res.memories;
    },
    enabled: !!botId,
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: string) =>
      apiFetch(`/api/v1/admin/memories/${memoryId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-memories"] });
    },
  });
}
