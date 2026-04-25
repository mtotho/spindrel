import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "../client";
import {
  adminMachineEnrollPath,
  adminMachineProfilePath,
  adminMachineProfilesPath,
  adminMachineTargetPath,
  adminMachineTargetSetupPath,
  adminMachinesPath,
  sessionMachineTargetLeasePath,
  sessionMachineTargetPath,
} from "@/src/lib/machineControlApiPaths";

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
  ready: boolean;
  status?: string | null;
  status_label?: string | null;
  reason?: string | null;
  checked_at?: string | null;
  handle_id?: string | null;
  connected: boolean;
  connection_id?: string | null;
  profile_id?: string | null;
  profile_label?: string | null;
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
  handle_id?: string | null;
  ready?: boolean;
  status?: string | null;
  status_label?: string | null;
  reason?: string | null;
  checked_at?: string | null;
  connection_id?: string | null;
  connected: boolean;
  provider_label?: string | null;
  target_label: string;
}

export interface SessionMachineTargetState {
  session_id: string;
  lease?: SessionMachineTargetLease | null;
  targets: MachineTarget[];
  ready_target_count?: number | null;
  connected_target_count?: number | null;
}

export interface MachineControlEnrollField {
  key: string;
  type?: string | null;
  label?: string | null;
  description?: string | null;
  required?: boolean;
  default?: string | number | boolean | null;
  secret?: boolean;
  multiline?: boolean;
  options?: Array<{ value: string; label: string }>;
}

export interface MachineProviderProfile {
  profile_id: string;
  label: string;
  summary?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  target_count: number;
  metadata?: Record<string, unknown> | null;
}

export interface MachineProviderState {
  provider_id: string;
  label: string;
  driver: string;
  integration_id: string;
  integration_name: string;
  integration_status: string;
  config_ready: boolean;
  supports_enroll: boolean;
  supports_remove_target: boolean;
  supports_profiles: boolean;
  integration_admin_href: string;
  enroll_fields?: MachineControlEnrollField[] | null;
  profile_fields?: MachineControlEnrollField[] | null;
  profiles?: MachineProviderProfile[] | null;
  profile_count?: number | null;
  metadata?: Record<string, unknown> | null;
  targets: MachineTarget[];
  target_count: number;
  ready_target_count: number;
  connected_target_count: number;
}

export interface MachineProviderListResponse {
  providers: MachineProviderState[];
}

export interface MachineTargetEnrollment {
  provider: Omit<MachineProviderState, "targets" | "target_count" | "ready_target_count" | "connected_target_count">;
  target: MachineTarget;
  launch?: {
    token?: string;
    websocket_path?: string;
    example_command?: string;
    install_systemd_user_command?: string;
  } | null;
  metadata?: Record<string, unknown> | null;
}

export interface MachineTargetSetupPayload {
  kind?: string | null;
  download_url?: string | null;
  websocket_path?: string | null;
  launch_command?: string | null;
  install_systemd_user_command?: string | null;
  notes?: string[] | null;
}

export interface MachineTargetSetupResult {
  provider: Omit<MachineProviderState, "targets" | "target_count" | "ready_target_count" | "connected_target_count">;
  target: MachineTarget;
  setup?: MachineTargetSetupPayload | null;
}

export interface MachineTargetProbeResult {
  provider: Omit<MachineProviderState, "targets" | "target_count" | "ready_target_count" | "connected_target_count">;
  target: MachineTarget;
}

export interface MachineProfileMutationResult {
  provider: Omit<MachineProviderState, "targets" | "target_count" | "ready_target_count" | "connected_target_count">;
  profile: MachineProviderProfile;
}

export function useSessionMachineTarget(sessionId: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["session-machine-target", sessionId ?? null],
    queryFn: () => apiFetch<SessionMachineTargetState>(sessionMachineTargetPath(String(sessionId))),
    enabled: enabled && !!sessionId,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
}

export function useGrantSessionMachineTargetLease(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider_id: string; target_id: string; ttl_seconds?: number }) =>
      apiFetch<SessionMachineTargetState>(sessionMachineTargetLeasePath(sessionId), {
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
      apiFetch<SessionMachineTargetState>(sessionMachineTargetLeasePath(sessionId), {
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
    queryFn: () => apiFetch<MachineProviderListResponse>(adminMachinesPath()),
    enabled,
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });
}

export function useEnrollMachineTarget(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { label?: string | null; config?: Record<string, unknown> | null }) =>
      apiFetch<MachineTargetEnrollment>(adminMachineEnrollPath(providerId), {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useProbeMachineTarget(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (targetId: string) =>
      apiFetch<MachineTargetProbeResult>(adminMachineTargetPath(providerId, targetId) + "/probe", {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useMachineTargetSetup(providerId: string) {
  return useMutation({
    mutationFn: (targetId: string) =>
      apiFetch<MachineTargetSetupResult>(adminMachineTargetSetupPath(providerId, targetId), {
        method: "POST",
      }),
  });
}

export function useProbeAnyMachineTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ providerId, targetId }: { providerId: string; targetId: string }) =>
      apiFetch<MachineTargetProbeResult>(adminMachineTargetPath(providerId, targetId) + "/probe", {
        method: "POST",
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
      apiFetch<{ status: string; provider_id: string; target_id: string }>(adminMachineTargetPath(providerId, targetId), {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useCreateMachineProfile(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { label?: string | null; config?: Record<string, unknown> | null }) =>
      apiFetch<MachineProfileMutationResult>(adminMachineProfilesPath(providerId), {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useUpdateMachineProfile(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      profileId,
      body,
    }: {
      profileId: string;
      body?: { label?: string | null; config?: Record<string, unknown> | null };
    }) =>
      apiFetch<MachineProfileMutationResult>(adminMachineProfilePath(providerId, profileId), {
        method: "PUT",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}

export function useDeleteMachineProfile(providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profileId: string) =>
      apiFetch<{ status: string; provider_id: string; profile_id: string }>(adminMachineProfilePath(providerId, profileId), {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-machines"] });
      qc.invalidateQueries({ queryKey: ["session-machine-target"] });
    },
  });
}
