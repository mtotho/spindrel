import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WidgetHealthSummary } from "@/src/types/api";

export interface WidgetHealthResponse {
  pin_id: string;
  health: WidgetHealthSummary | null;
}

export interface DashboardWidgetHealthResponse {
  dashboard_key: string;
  checked_count: number;
  total_pins: number;
  status: WidgetHealthSummary["status"] | "unknown";
  counts: Record<string, number>;
  results: WidgetHealthSummary[];
}

export function useWidgetHealth(pinId?: string | null) {
  return useQuery({
    queryKey: ["widget-health", pinId],
    queryFn: () => apiFetch<WidgetHealthResponse>(
      `/api/v1/widgets/dashboard/pins/${encodeURIComponent(pinId!)}/health`,
    ),
    enabled: !!pinId,
    staleTime: 30_000,
  });
}

export function useCheckWidgetHealth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ pinId, includeBrowser = true }: { pinId: string; includeBrowser?: boolean }) =>
      apiFetch<WidgetHealthSummary>(
        `/api/v1/widgets/dashboard/pins/${encodeURIComponent(pinId)}/health/check?include_browser=${includeBrowser ? "true" : "false"}`,
        { method: "POST" },
      ),
    onSuccess: (health) => {
      if (health.pin_id) {
        qc.setQueryData<WidgetHealthResponse>(
          ["widget-health", health.pin_id],
          { pin_id: health.pin_id, health },
        );
      }
    },
  });
}

export function useCheckDashboardWidgetHealth() {
  return useMutation({
    mutationFn: ({
      dashboardKey,
      limit = 20,
      includeBrowser = true,
    }: {
      dashboardKey: string;
      limit?: number;
      includeBrowser?: boolean;
    }) =>
      apiFetch<DashboardWidgetHealthResponse>(
        `/api/v1/widgets/dashboard/${encodeURIComponent(dashboardKey)}/health/check?limit=${limit}&include_browser=${includeBrowser ? "true" : "false"}`,
        { method: "POST" },
      ),
  });
}
