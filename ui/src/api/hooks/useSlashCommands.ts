import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../client";
import type { SlashCommandCatalog, SlashCommandSpec } from "../../types/api";

const FALLBACK_CATALOG: SlashCommandSpec[] = [];

/** Fetches the canonical slash-command catalog from the backend.
 *
 * The backend is the single source of truth for which commands exist, what
 * surfaces they apply to, and what args they accept. Keeping the frontend's
 * list derived from this endpoint prevents the two registries from drifting.
 *
 * When `botId` is provided, the catalog is intersected server-side with
 * the bot's runtime slash policy if the bot is a harness. Picker AND
 * `/help` consume the same intersection, so they stay in sync.
 */
export function useSlashCommandCatalog(botId?: string | null) {
  const qs = botId ? `?bot_id=${encodeURIComponent(botId)}` : "";
  return useQuery({
    queryKey: ["slash-commands", botId ?? null],
    queryFn: () => apiFetch<SlashCommandCatalog>(`/api/v1/slash-commands${qs}`),
    staleTime: 10 * 60 * 1000,
  });
}

export function useSlashCommandList(botId?: string | null): SlashCommandSpec[] {
  const query = useSlashCommandCatalog(botId);
  return query.data?.commands ?? FALLBACK_CATALOG;
}
