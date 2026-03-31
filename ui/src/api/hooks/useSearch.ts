import { useMutation } from "@tanstack/react-query";
import { apiFetch } from "../client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MemorySearchResult {
  file_path: string;
  content: string;
  score: number;
  bot_id: string;
  bot_name: string;
}

export interface MemorySearchResponse {
  results: MemorySearchResult[];
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useMemorySearch() {
  return useMutation({
    mutationFn: (body: {
      query: string;
      bot_ids?: string[];
      top_k?: number;
    }) =>
      apiFetch<MemorySearchResponse>("/api/v1/search/memory", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}
