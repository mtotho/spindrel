import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface Operation {
  id: string;
  type: string;
  label: string;
  current: number;
  total: number;
  status: "running" | "completed" | "failed";
  elapsed: number;
  message: string;
}

interface OperationsResponse {
  operations: Operation[];
}

export function useOperations(enabled = true) {
  return useQuery({
    queryKey: ["admin-diagnostics-operations"],
    queryFn: () => apiFetch<OperationsResponse>("/api/v1/admin/diagnostics/operations"),
    refetchInterval: 2_000,
    enabled,
    select: (data) => data.operations,
  });
}
