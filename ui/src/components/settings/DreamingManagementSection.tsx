/**
 * Embeds per-bot dreaming management + compact run history directly
 * in the Memory & Learning settings group.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Moon, AlertTriangle, ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import type { BotConfig } from "@/src/types/api";

const COMPACT_RUN_LIMIT = 5;

export function DreamingManagementSection() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data, isLoading } = useLearningOverview();
  const { data: bots } = useAdminBots();

  const botConfigMap = useMemo(() => {
    const map: Record<string, BotConfig> = {};
    if (bots) for (const b of bots) map[b.id] = b;
    return map;
  }, [bots]);

  const recentRuns = useMemo(
    () => (data?.recent_runs ?? []).slice(0, COMPACT_RUN_LIMIT),
    [data?.recent_runs]
  );

  // Quick status
  const maintEnabled = data?.bots.filter((b) => b.enabled).length ?? 0;
  const skillEnabled = data?.bots.filter((b) => b.skill_review_enabled).length ?? 0;
  const totalBots = data?.bots.length ?? 0;
  const failures =
    data?.bots.filter(
      (b) =>
        b.last_task_status === "failed" ||
        b.skill_review_last_task_status === "failed"
    ) ?? [];

  if (isLoading) {
    return (
      <div className="text-xs py-4 text-text-dim">Loading dreaming status...</div>
    );
  }
  if (!data) return null;

  return (
    <div className="flex flex-col gap-5 mt-4">
      {/* Section header */}
      <div className="flex flex-col gap-1">
        <div className="flex flex-row items-center gap-2">
          <Moon size={15} className="text-purple-400" />
          <span className="text-text text-sm font-semibold">
            Dreaming — Per-Bot Management
          </span>
        </div>
        <span className="text-text-dim text-xs leading-relaxed">
          Toggle dreaming per bot, trigger runs on demand. Click a bot name to
          open its Memory tab.
        </span>
      </div>

      {/* Quick status banner */}
      <div className="rounded-lg p-3 bg-surface-raised border border-surface-border">
        <div className="flex flex-col gap-1.5 text-[11px] text-text-muted">
          <div className="flex flex-row items-center gap-2">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background: maintEnabled > 0 ? t.warning : t.textDim,
              }}
            />
            <span>
              <strong className="text-text">
                {maintEnabled}/{totalBots}
              </strong>{" "}
              bots running maintenance
            </span>
          </div>
          <div className="flex flex-row items-center gap-2">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background: skillEnabled > 0 ? t.purple : t.textDim,
              }}
            />
            <span>
              <strong className="text-text">
                {skillEnabled}/{totalBots}
              </strong>{" "}
              bots running skill review
            </span>
          </div>
          {failures.length > 0 && (
            <div className="flex flex-row items-center gap-2 mt-0.5 text-danger">
              <AlertTriangle size={11} />
              <span>
                {failures.map((b) => b.bot_name).join(", ")}: last run failed
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Bot table */}
      <DreamingBotTable bots={data.bots} mode="manage" botConfigMap={botConfigMap} />

      {/* Compact recent runs */}
      {recentRuns.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center justify-between">
            <span className="text-text text-xs font-semibold">
              Recent Runs
            </span>
            <button
              type="button"
              onClick={() => navigate("/admin/learning#Dreaming")}
              className="flex flex-row items-center gap-1 text-[10px] text-accent hover:underline cursor-pointer bg-transparent border-none"
            >
              View full history
              <ExternalLink size={10} />
            </button>
          </div>
          <HygieneHistoryList runs={recentRuns} showBotName />
        </div>
      )}
    </div>
  );
}
