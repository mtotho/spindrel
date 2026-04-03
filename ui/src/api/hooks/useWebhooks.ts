import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface WebhookEndpointItem {
  id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface WebhookCreatePayload {
  name: string;
  url: string;
  events?: string[];
  is_active?: boolean;
  description?: string;
}

export interface WebhookCreateResponse {
  endpoint: WebhookEndpointItem;
  secret: string;
}

export interface WebhookUpdatePayload {
  name?: string;
  url?: string;
  events?: string[];
  is_active?: boolean;
  description?: string;
}

export interface WebhookEventType {
  event: string;
  description: string;
}

export interface WebhookDeliveryItem {
  id: string;
  endpoint_id: string;
  event: string;
  payload: Record<string, unknown>;
  attempt: number;
  status_code: number | null;
  response_body: string | null;
  error: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface WebhookTestResult {
  success: boolean;
  status_code: number | null;
  duration_ms: number;
  response_body?: string | null;
  error?: string | null;
}

export interface WebhookRotateSecretResponse {
  secret: string;
}

export function useWebhooks() {
  return useQuery({
    queryKey: ["admin-webhooks"],
    queryFn: () => apiFetch<WebhookEndpointItem[]>("/api/v1/admin/webhooks"),
  });
}

export function useWebhook(webhookId: string | undefined) {
  return useQuery({
    queryKey: ["admin-webhook", webhookId],
    queryFn: () => apiFetch<WebhookEndpointItem>(`/api/v1/admin/webhooks/${webhookId}`),
    enabled: !!webhookId && webhookId !== "new",
  });
}

export function useWebhookEvents() {
  return useQuery({
    queryKey: ["admin-webhook-events"],
    queryFn: () => apiFetch<WebhookEventType[]>("/api/v1/admin/webhooks/events"),
  });
}

export function useCreateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: WebhookCreatePayload) =>
      apiFetch<WebhookCreateResponse>("/api/v1/admin/webhooks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
    },
  });
}

export function useUpdateWebhook(webhookId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: WebhookUpdatePayload) =>
      apiFetch<WebhookEndpointItem>(`/api/v1/admin/webhooks/${webhookId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
      qc.invalidateQueries({ queryKey: ["admin-webhook", webhookId] });
    },
  });
}

export function useDeleteWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (webhookId: string) =>
      apiFetch(`/api/v1/admin/webhooks/${webhookId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-webhooks"] });
    },
  });
}

export function useRotateWebhookSecret(webhookId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<WebhookRotateSecretResponse>(`/api/v1/admin/webhooks/${webhookId}/rotate-secret`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-webhook", webhookId] });
    },
  });
}

export function useTestWebhook(webhookId: string | undefined) {
  return useMutation({
    mutationFn: () =>
      apiFetch<WebhookTestResult>(`/api/v1/admin/webhooks/${webhookId}/test`, {
        method: "POST",
      }),
  });
}

export function useWebhookDeliveries(
  webhookId: string | undefined,
  params?: { event?: string; limit?: number; offset?: number },
) {
  const searchParams = new URLSearchParams();
  if (params?.event) searchParams.set("event", params.event);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return useQuery({
    queryKey: ["admin-webhook-deliveries", webhookId, params],
    queryFn: () =>
      apiFetch<WebhookDeliveryItem[]>(
        `/api/v1/admin/webhooks/${webhookId}/deliveries${qs ? `?${qs}` : ""}`,
      ),
    enabled: !!webhookId && webhookId !== "new",
    refetchInterval: 10_000,
  });
}
