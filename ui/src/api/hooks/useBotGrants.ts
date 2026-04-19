import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import { useAuthStore } from "../../stores/auth";

export interface BotGrant {
  bot_id: string;
  user_id: string;
  user_display_name: string;
  user_email: string;
  role: string;
  granted_by: string | null;
  granted_by_display_name: string | null;
  created_at: string;
}

const grantsKey = (botId: string) => ["admin-bot-grants", botId] as const;

export function useBotGrants(botId: string | undefined, enabled: boolean = true) {
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  return useQuery({
    queryKey: grantsKey(botId ?? ""),
    queryFn: () =>
      apiFetch<BotGrant[]>(`/api/v1/admin/bots/${encodeURIComponent(botId!)}/grants`),
    enabled: enabled && isAdmin && !!botId,
    staleTime: 30_000,
  });
}

export function useCreateBotGrant(botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { user_id: string; role?: string }) =>
      apiFetch<BotGrant>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/grants`,
        { method: "POST", body: JSON.stringify({ role: "view", ...payload }) },
      ),
    onSuccess: () => {
      if (botId) qc.invalidateQueries({ queryKey: grantsKey(botId) });
    },
  });
}

export function useDeleteBotGrant(botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiFetch<void>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/grants/${encodeURIComponent(userId)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      if (botId) qc.invalidateQueries({ queryKey: grantsKey(botId) });
    },
  });
}

export function useBulkCreateBotGrants(botId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userIds: string[]) =>
      apiFetch<BotGrant[]>(
        `/api/v1/admin/bots/${encodeURIComponent(botId!)}/grants/bulk`,
        { method: "POST", body: JSON.stringify({ user_ids: userIds, role: "view" }) },
      ),
    onSuccess: () => {
      if (botId) qc.invalidateQueries({ queryKey: grantsKey(botId) });
    },
  });
}
