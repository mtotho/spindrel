import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../client";

interface MemorySchemeDefaults {
  prompt: string;
  flush_prompt: string;
}

export function useMemorySchemeDefaults() {
  return useQuery({
    queryKey: ["memory-scheme-defaults"],
    queryFn: () =>
      apiFetch<MemorySchemeDefaults>(
        "/api/v1/admin/settings/memory-scheme-defaults"
      ),
    staleTime: Infinity,
  });
}
