import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { BotConfig } from "../../types/api";

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
