import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { BotConfig, BotEditorData } from "../../types/api";

export interface SandboxStatus {
  exists: boolean;
  status?: string | null;
  container_name?: string | null;
  container_id?: string | null;
  image_id?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
}

export function useBots() {
  return useQuery({
    queryKey: ["bots"],
    queryFn: () => apiFetch<BotConfig[]>("/bots"),
  });
}

/** Full bot configs via admin endpoint (includes tools, skills, memory, etc.) */
export function useAdminBots() {
  return useQuery({
    queryKey: ["admin-bots"],
    queryFn: async () => {
      const res = await apiFetch<{ bots: BotConfig[] }>("/api/v1/admin/bots");
      return res.bots;
    },
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

export function useBotSandboxStatus(botId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["bot-sandbox", botId],
    queryFn: () => apiFetch<SandboxStatus>(`/api/v1/admin/bots/${botId}/sandbox`),
    enabled: !!botId && enabled,
    refetchInterval: 30_000,
  });
}

export function useRecreateBotSandbox(botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/admin/bots/${botId}/sandbox/recreate`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-sandbox", botId] });
    },
  });
}
