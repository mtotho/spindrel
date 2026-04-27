import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type {
  NotificationDeliveryList,
  NotificationTarget,
  NotificationTargetCreate,
  NotificationTargetUpdate,
  NotificationTargetDestinations,
} from "../../types/api";

export function useNotificationTargets() {
  return useQuery({
    queryKey: ["notification-targets"],
    queryFn: async () => {
      const res = await apiFetch<{ targets: NotificationTarget[] }>("/api/v1/admin/notification-targets");
      return res.targets;
    },
  });
}

export function useNotificationDestinations() {
  return useQuery({
    queryKey: ["notification-target-destinations"],
    queryFn: () => apiFetch<NotificationTargetDestinations>("/api/v1/admin/notification-targets/available-destinations"),
  });
}

export function useCreateNotificationTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NotificationTargetCreate) =>
      apiFetch<NotificationTarget>("/api/v1/admin/notification-targets", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-targets"] });
    },
  });
}

export function useUpdateNotificationTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: NotificationTargetUpdate }) =>
      apiFetch<NotificationTarget>(`/api/v1/admin/notification-targets/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-targets"] });
    },
  });
}

export function useDeleteNotificationTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(`/api/v1/admin/notification-targets/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-targets"] });
    },
  });
}

export function useTestNotificationTarget() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/api/v1/admin/notification-targets/${id}/test`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-deliveries"] });
    },
  });
}

export function useNotificationDeliveries(page = 1, pageSize = 20) {
  return useQuery({
    queryKey: ["notification-deliveries", page, pageSize],
    queryFn: () =>
      apiFetch<NotificationDeliveryList>(
        `/api/v1/admin/notification-targets/deliveries?page=${page}&page_size=${pageSize}`,
      ),
  });
}
