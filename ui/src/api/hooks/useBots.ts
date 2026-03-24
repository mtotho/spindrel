import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { BotConfig, BotEditorData } from "../../types/api";

export function useBots() {
  return useQuery({
    queryKey: ["bots"],
    queryFn: () => apiFetch<BotConfig[]>("/bots"),
  });
}

export function useBot(botId: string | undefined) {
  return useQuery({
    queryKey: ["bots", botId],
    queryFn: () => apiFetch<BotConfig>(`/api/v1/admin/bots/${botId}`),
    enabled: !!botId,
  });
}

export function useBotEditorData(botId: string | undefined) {
  return useQuery({
    queryKey: ["bot-editor", botId],
    queryFn: () => apiFetch<BotEditorData>(`/api/v1/admin/bots/${botId}/editor-data`),
    enabled: !!botId,
  });
}

export function useUpdateBot(botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<BotConfig>) =>
      apiFetch<BotConfig>(`/api/v1/admin/bots/${botId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots", botId] });
      qc.invalidateQueries({ queryKey: ["bot-editor", botId] });
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}

export function useCreateBot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<BotConfig> & { id: string; name: string; model: string }) =>
      apiFetch<BotConfig>("/api/v1/admin/bots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bots"] });
    },
  });
}
