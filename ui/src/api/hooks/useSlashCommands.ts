import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../client";
import type { SlashCommandCatalog, SlashCommandSpec } from "../../types/api";

const FALLBACK_CATALOG: SlashCommandSpec[] = [];

/** Fetches the canonical slash-command catalog from the backend.
 *
 * The backend is the single source of truth for which commands exist, what
 * surfaces they apply to, and what args they accept. Keeping the frontend's
 * list derived from this endpoint prevents the two registries from drifting.
 */
export function useSlashCommandCatalog() {
  return useQuery({
    queryKey: ["slash-commands"],
    queryFn: () => apiFetch<SlashCommandCatalog>("/api/v1/slash-commands"),
    staleTime: 10 * 60 * 1000,
  });
}

export function useSlashCommandList(): SlashCommandSpec[] {
  const query = useSlashCommandCatalog();
  return query.data?.commands ?? FALLBACK_CATALOG;
}
