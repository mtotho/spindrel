import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../lib/api";

export function useOverview(scope?: string) {
  return useQuery({
    queryKey: ["overview", scope],
    queryFn: () => fetchOverview(scope),
    refetchInterval: 60_000,
  });
}
