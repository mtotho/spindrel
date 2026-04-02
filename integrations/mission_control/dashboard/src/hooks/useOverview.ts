import { useQuery } from "@tanstack/react-query";
import { fetchOverview } from "../lib/api";

export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: 60_000,
  });
}
