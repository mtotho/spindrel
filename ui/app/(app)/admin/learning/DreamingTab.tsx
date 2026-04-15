import { useMemo, useState } from "react";
import { Moon, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import type { BotConfig } from "@/src/types/api";

type RunFilter = "all" | "memory_hygiene" | "skill_review";

export function DreamingTab() {
  const t = useThemeTokens();
  const { data, isLoading } = useLearningOverview();
  const { data: bots } = useAdminBots();
  const [runFilter, setRunFilter] = useState<RunFilter>("all");

  const botConfigMap = useMemo(() => {
    const map: Record<string, BotConfig> = {};
    if (bots) for (const b of bots) map[b.id] = b;
    return map;
  }, [bots]);

  const filteredRuns = useMemo(() => {
    if (!data?.recent_runs) return [];
    if (runFilter === "all") return data.recent_runs;
    return data.recent_runs.filter((r) => r.job_type === runFilter);
  }, [data?.recent_runs, runFilter]);

  // Quick status counts
  const maintEnabled = data?.bots.filter((b) => b.enabled).length ?? 0;
  const skillEnabled = data?.bots.filter((b) => b.skill_review_enabled).length ?? 0;
  const totalBots = data?.bots.length ?? 0;
  const failures = data?.bots.filter(
    (b) => b.last_task_status === "failed" || b.skill_review_last_task_status === "failed"
  ) ?? [];

  if (isLoading) {
    return <div className="text-xs p-5" style={{ color: t.textDim }}>Loading...</div>;
  }
  if (!data) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Quick Status Banner */}
      <div style={{ borderRadius: 8, padding: 12, background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}` }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11, color: t.textMuted }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: maintEnabled > 0 ? "#f59e0b" : t.textDim }} />
            <span>
              <strong style={{ color: t.text }}>{maintEnabled}/{totalBots}</strong> bots running maintenance
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: skillEnabled > 0 ? "#8b5cf6" : t.textDim }} />
            <span>
              <strong style={{ color: t.text }}>{skillEnabled}/{totalBots}</strong> bots running skill review
            </span>
          </div>
          {failures.length > 0 && (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 2, color: t.danger }}>
              <AlertTriangle size={11} />
              <span>{failures.map((b) => b.bot_name).join(", ")}: last run failed</span>
            </div>
          )}
        </div>
      </div>

      {/* Per-bot dreaming management */}
      <div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <Moon size={14} color="#8b5cf6" />
          <span className="text-sm font-semibold" style={{ color: t.text }}>Dreaming by Bot</span>
        </div>
        <span className="text-[11px] block mb-3" style={{ color: t.textDim, lineHeight: "17px" }}>
          Toggle dreaming per bot. &ldquo;Inherit&rdquo; uses the global default.
          Click a bot name to open its Memory tab.
        </span>

        <DreamingBotTable bots={data.bots} mode="manage" botConfigMap={botConfigMap} />
      </div>

      {/* Run history with filter */}
      {data.recent_runs.length > 0 && (
        <div>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <span className="text-sm font-semibold" style={{ color: t.text }}>Recent Runs</span>
            <div style={{ display: "flex", flexDirection: "row", gap: 2, padding: 2, borderRadius: 6, background: t.surfaceOverlay }}>
              {([
                { key: "all" as const, label: "All" },
                { key: "memory_hygiene" as const, label: "Maintenance" },
                { key: "skill_review" as const, label: "Skill Review" },
              ]).map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setRunFilter(key)}
                  className="px-2 py-0.5 rounded text-[10px] cursor-pointer transition-colors"
                  style={{
                    fontWeight: runFilter === key ? 700 : 400,
                    color: runFilter === key ? t.text : t.textDim,
                    background: runFilter === key ? t.surfaceRaised : "transparent",
                    border: runFilter === key ? `1px solid ${t.surfaceBorder}` : "1px solid transparent",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <HygieneHistoryList runs={filteredRuns} showBotName />
        </div>
      )}
    </div>
  );
}
