import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface FallbackEvent {
  id: string;
  model: string;
  fallback_model: string;
  reason: string;
  error_message?: string | null;
  session_id?: string | null;
  channel_id?: string | null;
  bot_id?: string | null;
  cooldown_until?: string | null;
  created_at?: string | null;
}

export interface Cooldown {
  model: string;
  fallback_model: string;
  expires_at: string;
  remaining_seconds: number;
}

export interface FallbacksParams {
  model?: string;
  bot_id?: string;
  count?: number;
}

export function useFallbackEvents(params: FallbacksParams = {}) {
  const qs = new URLSearchParams();
  if (params.model) qs.set("model", params.model);
  if (params.bot_id) qs.set("bot_id", params.bot_id);
  if (params.count) qs.set("count", String(params.count));
  const query = qs.toString();

  return useQuery({
    queryKey: ["admin-fallbacks", params],
    queryFn: () =>
      apiFetch<{ events: FallbackEvent[] }>(
        `/api/v1/admin/fallbacks${query ? `?${query}` : ""}`
      ),
  });
}

export function useFallbackCooldowns() {
  return useQuery({
    queryKey: ["admin-fallback-cooldowns"],
    queryFn: () =>
      apiFetch<{ cooldowns: Cooldown[] }>("/api/v1/admin/fallbacks/cooldowns"),
    refetchInterval: 15000, // auto-refresh every 15s
  });
}

export function useClearCooldown() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (model: string) =>
      apiFetch(`/api/v1/admin/fallbacks/cooldowns/${encodeURIComponent(model)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-fallback-cooldowns"] });
    },
  });
}
