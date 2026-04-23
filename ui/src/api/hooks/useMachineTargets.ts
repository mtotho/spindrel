import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../client";

export interface MachineTarget {
  provider_id: string;
  provider_label?: string | null;
  target_id: string;
  driver: string;
  label: string;
  hostname: string;
  platform: string;
  capabilities: string[];
  enrolled_at?: string | null;
  last_seen_at?: string | null;
  connected: boolean;
  connection_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface SessionMachineTargetLease {
  lease_id: string;
  provider_id: string;
  target_id: string;
  user_id: string;
  granted_at: string;
  expires_at: string;
  capabilities: string[];
  connection_id?: string | null;
  connected: boolean;
  provider_label?: string | null;
  target_label: string;
}

export interface SessionMachineTargetState {
  session_id: string;
  lease?: SessionMachineTargetLease | null;
  targets: MachineTarget[];
}

export interface MachineProviderState {
  provider_id: string;
  label: string;
  driver: string;
  integration_id: string;
  integration_name: string;
  integration_status: string;
  supports_enroll: boolean;
  supports_remove_target: boolean;
  integration_admin_href: string;
  metadata?: Record<string, unknown> | null;
  targets: MachineTarget[];
  target_count: number;
  connected_target_count: number;
}

export interface MachineProviderListResponse {
  providers: MachineProviderState[];
}

export interface MachineTargetEnrollment {
  provider: Omit<MachineProviderState, "targets" | "target_count" | "connected_target_count">;
  target: MachineTarget;
  launch?: {
    token?: string;
    websocket_path?: string;
    example_command?: string;
  } | null;
  metadata?: Record<string, unknown> | null;
}

export function useSessionMachineTarget(sessionId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["session-machine-target", sessionId ?? null],
    queryFn: () => apiFetch<SessionMachineTargetState>(`/sessions/${sessionId}/machine-target`),
    enabled: enabled && !!sessionId,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
}

export function useGrantSessionMachineTargetLease(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider_id: string; target_id: string; ttl_seconds?: number }) =>
      apiFetch<SessionMachineTargetState>(`/sessions/${sessionId}/machine-target/lease`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-machine-target", sessionId] });
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
    },
  });
}

export function useClearSessionMachineTargetLease(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionMachineTargetState>(`/sessions/${sessionId}/machine-target/lease`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-machine-target", sessionId] });
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
    },
  });
}

export function useAdminMachines(enabled = true) {
  return useQuery({
    queryKey: ["admin-machines"],
    queryFn: () => apiFetch<MachineProviderListResponse>("/admin/machines"),
    enabled,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

export function useEnrollMachineTarget(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { label?: string | null }) =>
      apiFetch<MachineTargetEnrollment>(`/admin/machines/providers/${encodeURIComponent(providerId)}/enroll`, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useDeleteMachineTarget(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (targetId: string) =>
      apiFetch<{ status: string; provider_id: string; target_id: string }>(
        `/admin/machines/providers/${encodeURIComponent(providerId)}/targets/${encodeURIComponent(targetId)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}
