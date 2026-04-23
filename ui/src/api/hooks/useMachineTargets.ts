import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../client";

export interface MachineTarget {
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
}

export interface SessionMachineTargetLease {
  lease_id: string;
  target_id: string;
  user_id: string;
  granted_at: string;
  expires_at: string;
  capabilities: string[];
  connection_id?: string | null;
  connected: boolean;
  target_label: string;
}

export interface SessionMachineTargetState {
  session_id: string;
  lease?: SessionMachineTargetLease | null;
  targets: MachineTarget[];
}

export interface LocalCompanionEnrollment {
  target: MachineTarget;
  token: string;
  example_command: string;
  websocket_path: string;
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
    mutationFn: (body: { target_id: string; ttl_seconds?: number }) =>
      apiFetch<SessionMachineTargetState>(`/sessions/${sessionId}/machine-target/lease`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-machine-target", sessionId] });
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
    },
  });
}

export function useEnrollLocalCompanion(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { label?: string | null }) =>
      apiFetch<LocalCompanionEnrollment>("/integrations/local_companion/admin/enroll", {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-machine-target", sessionId] });
    },
  });
}

export function useDeleteLocalCompanionTarget(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (targetId: string) =>
      apiFetch<{ status: string; target_id: string }>(
        `/integrations/local_companion/admin/targets/${encodeURIComponent(targetId)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session-machine-target", sessionId] });
    },
  });
}
