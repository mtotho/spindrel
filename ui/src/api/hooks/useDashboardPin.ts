import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";
import type { WidgetDashboardPin } from "../../types/api";

export function useDashboardPin(pinId: string | undefined) {
  return useQuery({
    queryKey: ["dashboard-pin", pinId],
    queryFn: () =>
      apiFetch<WidgetDashboardPin>(
        `/api/v1/widgets/dashboard/pins/${encodeURIComponent(pinId!)}`,
      ),
    enabled: !!pinId,
  });
}

