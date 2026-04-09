import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface BotHookItem {
  id: string;
  bot_id: string;
  name: string;
  trigger: string;
  conditions: Record<string, string>;
  command: string;
  cooldown_seconds: number;
  on_failure: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface BotHookCreatePayload {
  bot_id: string;
  name: string;
  trigger: string;
  conditions?: Record<string, string>;
  command: string;
  cooldown_seconds?: number;
  on_failure?: string;
  enabled?: boolean;
}

export interface BotHookUpdatePayload {
  name?: string;
  trigger?: string;
  conditions?: Record<string, string>;
  command?: string;
  cooldown_seconds?: number;
  on_failure?: string;
  enabled?: boolean;
}

export function useBotHooks(botId?: string) {
  const qs = botId ? `?bot_id=${encodeURIComponent(botId)}` : "";
  return useQuery({
    queryKey: ["bot-hooks", botId],
    queryFn: () => apiFetch<BotHookItem[]>(`/api/v1/bot-hooks${qs}`),
    enabled: !!botId,
  });
}

export function useCreateBotHook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: BotHookCreatePayload) =>
      apiFetch<BotHookItem>("/api/v1/bot-hooks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ["bot-hooks", variables.bot_id] });
    },
  });
}

export function useUpdateBotHook(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ hookId, data }: { hookId: string; data: BotHookUpdatePayload }) =>
      apiFetch<BotHookItem>(`/api/v1/bot-hooks/${hookId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-hooks", botId] });
    },
  });
}

export function useDeleteBotHook(botId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (hookId: string) =>
      apiFetch(`/api/v1/bot-hooks/${hookId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bot-hooks", botId] });
    },
  });
}
