import { useMemo } from "react";
import { Moon } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { DreamingBotTable } from "@/src/components/learning/DreamingBotTable";
import type { BotConfig } from "@/src/types/api";

export function DreamingTab() {
  const t = useThemeTokens();
  const { data, isLoading } = useLearningOverview();
  const { data: bots } = useAdminBots();

  const botConfigMap = useMemo(() => {
    const map: Record<string, BotConfig> = {};
    if (bots) for (const b of bots) map[b.id] = b;
    return map;
  }, [bots]);

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12, padding: 20 }}>Loading...</div>;
  }
  if (!data) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Per-bot dreaming management — canonical surface for toggles + Run */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <Moon size={14} color="#8b5cf6" />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Dreaming by Bot</span>
        </div>
        <span style={{ fontSize: 11, color: t.textDim, lineHeight: "17px", display: "block", marginBottom: 12 }}>
          Toggle dreaming per bot. &ldquo;Inherit&rdquo; uses the global default.
          Click a bot name to open its Memory tab.
        </span>

        <DreamingBotTable bots={data.bots} mode="manage" botConfigMap={botConfigMap} />
      </div>

      {/* Full run timeline */}
      {data.recent_runs.length > 0 && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: t.text, marginBottom: 10 }}>
            Recent Runs
          </div>
          <HygieneHistoryList runs={data.recent_runs} showBotName />
        </div>
      )}
    </div>
  );
}
