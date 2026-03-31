import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "../../stores/auth";

interface HealthResponse {
  status: string;
  version: string;
}

export function useVersion() {
  const serverUrl = useAuthStore((s) => s.serverUrl);

  return useQuery({
    queryKey: ["health-version"],
    queryFn: async () => {
      const res = await fetch(`${serverUrl}/health`);
      if (!res.ok) throw new Error("Health check failed");
      const data: HealthResponse = await res.json();
      return data.version;
    },
    enabled: !!serverUrl,
    staleTime: 300_000, // 5 min
    refetchInterval: 300_000,
  });
}
