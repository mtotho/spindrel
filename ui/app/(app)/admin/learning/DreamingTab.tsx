import { useMemo } from "react";
import { useRouter } from "expo-router";
import { useWindowDimensions } from "react-native";
import { Moon, Play } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useLearningOverview } from "@/src/api/hooks/useLearningOverview";
import { useTriggerMemoryHygiene } from "@/src/api/hooks/useMemoryHygiene";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { HygieneHistoryList } from "@/app/(app)/admin/bots/[botId]/HygieneHistoryList";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import { fmtRelative } from "@/app/(app)/admin/bots/[botId]/LearningSection";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import type { BotConfig } from "@/src/types/api";

type HygieneState = "inherit" | "on" | "off";
const STATES: HygieneState[] = ["inherit", "on", "off"];

function resolveState(val: boolean | null | undefined): HygieneState {
  if (val === true) return "on";
  if (val === false) return "off";
  return "inherit";
}

function stateToValue(s: HygieneState): boolean | null {
  if (s === "on") return true;
  if (s === "off") return false;
  return null;
}

export function DreamingTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;
  const { data, isLoading } = useLearningOverview();
  const { data: bots } = useAdminBots();
  const triggerMut = useTriggerMemoryHygiene();
  const qc = useQueryClient();

  const updateMut = useMutation({
    mutationFn: ({ botId, value }: { botId: string; value: boolean | null }) =>
      apiFetch<BotConfig>(`/api/v1/admin/bots/${botId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ memory_hygiene_enabled: value }),
      }),
    onSuccess: (_data, { botId }) => {
      qc.invalidateQueries({ queryKey: ["bots", botId] });
      qc.invalidateQueries({ queryKey: ["admin-bots"] });
      qc.invalidateQueries({ queryKey: ["learning-overview"] });
    },
  });

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
      {/* Per-bot dreaming config */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <Moon size={14} color="#8b5cf6" />
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Dreaming by Bot</span>
        </div>
        <span style={{ fontSize: 11, color: t.textDim, lineHeight: "17px", display: "block", marginBottom: 12 }}>
          Toggle dreaming per bot. &ldquo;Inherit&rdquo; uses the global default.
          Click a bot name to open its Memory tab.
        </span>

        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.bots.map((bot) => {
            const cfg = botConfigMap[bot.bot_id];
            const current = cfg ? resolveState(cfg.memory_hygiene_enabled) : "inherit";
            return (
              <div
                key={bot.bot_id}
                style={{
                  display: "flex",
                  flexDirection: isMobile ? "column" : "row",
                  alignItems: isMobile ? "stretch" : "center",
                  gap: isMobile ? 8 : 10,
                  backgroundColor: t.surfaceRaised,
                  borderRadius: 8,
                  border: `1px solid ${t.surfaceOverlay}`,
                  padding: isMobile ? "10px 12px" : "8px 12px",
                }}
              >
                {/* Top row: bot name + status */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
                  <button
                    onClick={() => router.push(`/admin/bots/${bot.bot_id}#memory` as any)}
                    style={{
                      flex: 1, textAlign: "left", cursor: "pointer",
                      background: "none", border: "none", padding: 0,
                    }}
                  >
                    <span style={{ color: t.text, fontSize: 13, fontWeight: 500 }}>
                      {bot.bot_name}
                    </span>
                  </button>

                  {/* Status info */}
                  <span style={{ fontSize: 10, color: t.textDim, whiteSpace: "nowrap" }}>
                    {fmtRelative(bot.last_run_at)}
                  </span>
                  {bot.last_task_status && (
                    <StatusBadge
                      label={bot.last_task_status}
                      variant={bot.last_task_status === "complete" ? "success" : bot.last_task_status === "failed" ? "danger" : "neutral"}
                    />
                  )}
                </div>

                {/* Controls row */}
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  {/* Toggle */}
                  <div style={{ display: "flex", gap: 4 }}>
                    {STATES.map((s) => {
                      const isSelected = current === s;
                      return (
                        <button
                          key={s}
                          disabled={updateMut.isPending}
                          onClick={() => {
                            if (!isSelected) updateMut.mutate({ botId: bot.bot_id, value: stateToValue(s) });
                          }}
                          style={{
                            padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 500,
                            cursor: isSelected ? "default" : "pointer",
                            border: isSelected ? `1px solid ${t.purpleBorder}` : `1px solid ${t.surfaceOverlay}`,
                            background: isSelected ? t.purpleSubtle : "transparent",
                            color: isSelected ? t.purple : t.textDim,
                            opacity: updateMut.isPending ? 0.6 : 1,
                            textTransform: "capitalize",
                          }}
                        >
                          {s}
                        </button>
                      );
                    })}
                  </div>

                  {/* Run Now */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (bot.enabled) triggerMut.mutate(bot.bot_id, {
                        onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                      });
                    }}
                    disabled={!bot.enabled || triggerMut.isPending}
                    title={bot.enabled ? "Trigger dreaming run now" : "Dreaming is disabled for this bot"}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 500,
                      background: bot.enabled ? "rgba(139,92,246,0.1)" : "transparent",
                      color: bot.enabled ? "#8b5cf6" : t.textDim,
                      border: `1px solid ${bot.enabled ? "rgba(139,92,246,0.25)" : t.surfaceOverlay}`,
                      cursor: bot.enabled ? "pointer" : "not-allowed",
                      opacity: triggerMut.isPending ? 0.6 : 1,
                    }}
                  >
                    <Play size={10} /> Run
                  </button>
                </div>
              </div>
            );
          })}
        </div>
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
