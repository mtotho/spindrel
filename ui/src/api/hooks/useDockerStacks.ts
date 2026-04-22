import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { DockerStack, DockerStackServiceStatus } from "../../types/api";

export function useDockerStacks(filters?: {
  bot_id?: string;
  channel_id?: string;
  status?: string;
}, enabled = true) {
  const params = new URLSearchParams();
  if (filters?.bot_id) params.set("bot_id", filters.bot_id);
  if (filters?.channel_id) params.set("channel_id", filters.channel_id);
  if (filters?.status) params.set("status", filters.status);
  const qs = params.toString();
  return useQuery({
    queryKey: ["docker-stacks", filters],
    queryFn: () =>
      apiFetch<DockerStack[]>(
        `/api/v1/admin/docker-stacks${qs ? `?${qs}` : ""}`
      ),
    enabled,
    refetchInterval: 15000,
  });
}

export function useDockerStack(stackId: string | undefined) {
  return useQuery({
    queryKey: ["docker-stacks", stackId],
    queryFn: () =>
      apiFetch<DockerStack>(`/api/v1/admin/docker-stacks/${stackId}`),
    enabled: !!stackId,
  });
}

export function useDockerStackStatus(stackId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["docker-stacks", stackId, "status"],
    queryFn: () =>
      apiFetch<DockerStackServiceStatus[]>(
        `/api/v1/admin/docker-stacks/${stackId}/status`
      ),
    enabled: !!stackId && enabled,
    refetchInterval: 5000,
  });
}

export function useDockerStackLogs(
  stackId: string | undefined,
  service?: string,
  tail = 100
) {
  const params = new URLSearchParams();
  if (service) params.set("service", service);
  params.set("tail", String(tail));
  return useQuery({
    queryKey: ["docker-stacks", stackId, "logs", service, tail],
    queryFn: () =>
      apiFetch<{ logs: string }>(
        `/api/v1/admin/docker-stacks/${stackId}/logs?${params}`
      ),
    enabled: !!stackId,
    refetchInterval: 10000,
  });
}

export function useStartDockerStack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stackId: string) =>
      apiFetch<DockerStack>(
        `/api/v1/admin/docker-stacks/${stackId}/start`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docker-stacks"] });
    },
  });
}

export function useStopDockerStack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stackId: string) =>
      apiFetch<DockerStack>(
        `/api/v1/admin/docker-stacks/${stackId}/stop`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docker-stacks"] });
    },
  });
}

export function useDestroyDockerStack() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stackId: string) =>
      apiFetch<void>(`/api/v1/admin/docker-stacks/${stackId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["docker-stacks"] });
    },
  });
}
