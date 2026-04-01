import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface ForecastComponent {
  source: "heartbeats" | "recurring_tasks" | "trajectory" | "fixed_plans";
  label: string;
  daily_cost: number;
  monthly_cost: number;
  count?: number | null;
  avg_cost_per_run?: number | null;
}

export interface LimitForecast {
  scope_type: string;
  scope_value: string;
  period: string;
  limit_usd: number;
  current_spend: number;
  percentage: number;
  projected_spend: number;
  projected_percentage: number;
}

export interface UsageForecast {
  daily_spend: number;
  monthly_spend: number;
  projected_daily: number;
  projected_monthly: number;
  components: ForecastComponent[];
  limits: LimitForecast[];
  computed_at: string;
  hours_elapsed_today: number;
}

export function useUsageForecast() {
  return useQuery({
    queryKey: ["usage-forecast"],
    queryFn: () => apiFetch<UsageForecast>("/api/v1/admin/usage/forecast"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
