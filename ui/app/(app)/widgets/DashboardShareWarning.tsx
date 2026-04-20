import { useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useDashboardPins } from "@/src/api/hooks/useDashboardPins";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useAuthStore } from "@/src/stores/auth";
import {
  computeCoverageGaps,
  dashboardBotIds,
  summarizeCoverageGaps,
  type BotGrantLookup,
} from "@/src/lib/dashboardBotCoverage";
import type { BotGrant } from "@/src/api/hooks/useBotGrants";

interface BotSummary {
  id: string;
  name: string;
  user_id?: string | null;
  display_name?: string | null;
}

function useAllBots() {
  const isAdmin = !!useAuthStore((s) => s.user?.is_admin);
  return useQuery({
    queryKey: ["admin-bots-summary"],
    queryFn: () => apiFetch<{ bots: BotSummary[] }>("/api/v1/admin/bots"),
    enabled: isAdmin,
    staleTime: 60_000,
  });
}

/** Fetches per-bot grants only for the bots that actually appear on the
 *  dashboard so we don't burn requests when admins tweak unrelated settings. */
function useGrantsForBots(botIds: string[], enabled: boolean) {
  return useQuery({
    queryKey: ["admin-bot-grants-bulk", [...botIds].sort()],
    queryFn: async () => {
      const out: Record<string, BotGrant[]> = {};
      await Promise.all(
        botIds.map(async (id) => {
          out[id] = await apiFetch<BotGrant[]>(
            `/api/v1/admin/bots/${encodeURIComponent(id)}/grants`,
          );
        }),
      );
      return out;
    },
    enabled: enabled && botIds.length > 0,
    staleTime: 30_000,
  });
}

/** When a non-admin viewer opens this dashboard, they'll 403 on any widget
 *  whose emitting bot hasn't granted them access. Surfaces a single warning
 *  with a one-click "grant access to all" button for the gap set. */
export function DashboardShareWarning({
  slug,
  railChoice,
}: {
  slug: string;
  railChoice: "off" | "me" | "everyone";
}) {
  const qc = useQueryClient();
  const { pins, isLoading: pinsLoading } = useDashboardPins(slug);
  const { data: users } = useAdminUsers();
  const { data: botsData } = useAllBots();

  const activeBotIds = useMemo(() => dashboardBotIds(pins), [pins]);
  const { data: grantsByBot, isLoading: grantsLoading } = useGrantsForBots(
    activeBotIds,
    railChoice === "everyone",
  );

  const bulkGrant = useMutation({
    mutationFn: async (
      entries: { bot_id: string; user_ids: string[] }[],
    ) => {
      await Promise.all(
        entries.map((entry) =>
          apiFetch<BotGrant[]>(
            `/api/v1/admin/bots/${encodeURIComponent(entry.bot_id)}/grants/bulk`,
            { method: "POST", body: JSON.stringify({ user_ids: entry.user_ids, role: "view" }) },
          ),
        ),
      );
    },
    onSuccess: () => {
      for (const bot_id of activeBotIds) {
        qc.invalidateQueries({ queryKey: ["admin-bot-grants", bot_id] });
      }
      qc.invalidateQueries({ queryKey: ["admin-bot-grants-bulk"] });
    },
  });

  const lookup: BotGrantLookup = useMemo(() => {
    const grants: Record<string, Set<string>> = {};
    const owners: Record<string, string | null> = {};
    const botMap = new Map((botsData?.bots ?? []).map((b) => [b.id, b]));
    for (const id of activeBotIds) {
      grants[id] = new Set((grantsByBot?.[id] ?? []).map((g) => g.user_id));
      owners[id] = botMap.get(id)?.user_id ?? null;
    }
    return { grants, owners };
  }, [activeBotIds, grantsByBot, botsData]);

  const gaps = useMemo(() => {
    if (railChoice !== "everyone") return [];
    if (!users) return [];
    return computeCoverageGaps(pins, users, lookup);
  }, [railChoice, users, pins, lookup]);

  if (railChoice !== "everyone") return null;
  if (pinsLoading) return null;
  if (activeBotIds.length === 0) return null;
  if (grantsLoading || !users || !botsData) return null;
  if (gaps.length === 0) return null;

  const botLabel = (id: string) => {
    const bot = botsData.bots.find((b) => b.id === id);
    return bot?.display_name || bot?.name || id;
  };
  const message = summarizeCoverageGaps(gaps, users, botLabel);

  const entries = gaps.map((g) => ({ bot_id: g.bot_id, user_ids: g.missing_user_ids }));

  return (
    <div className="flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800 dark:border-amber-400/40 dark:bg-amber-500/[0.08] dark:text-amber-100">
      <div className="flex flex-row items-start gap-2">
        <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-500 dark:text-amber-300" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-amber-800 dark:text-amber-200">Heads up — {message}.</div>
          <div className="mt-0.5 text-[11px] text-amber-700/80 dark:text-amber-200/80">
            Grant access so everyone with this dashboard pinned can load its
            widgets. You can fine-tune per-bot later in Admin → Bots.
          </div>
        </div>
      </div>
      <div className="flex flex-row justify-end gap-2">
        <button
          type="button"
          onClick={() => bulkGrant.mutate(entries)}
          disabled={bulkGrant.isPending}
          className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2.5 py-1 text-[11px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50 dark:bg-amber-500/80 dark:text-amber-950"
        >
          {bulkGrant.isPending ? "Granting…" : "Grant access to all"}
        </button>
      </div>
      {bulkGrant.isError && (
        <div className="text-[11px] text-red-600 dark:text-red-300">
          {(bulkGrant.error as Error)?.message ?? "Grant failed."}
        </div>
      )}
    </div>
  );
}
