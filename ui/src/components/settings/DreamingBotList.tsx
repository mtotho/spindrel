import { useMemo } from "react";
import { Moon } from "lucide-react";
import { useRouter } from "expo-router";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import type { BotConfig } from "@/src/types/api";

type HygieneState = "inherit" | "on" | "off";

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

const STATES: HygieneState[] = ["inherit", "on", "off"];

export function DreamingBotList() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: bots } = useAdminBots();
  const qc = useQueryClient();

  const sortedBots = useMemo(() => {
    if (!bots) return [];
    return [...bots].sort((a, b) => a.name.localeCompare(b.name));
  }, [bots]);

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
    },
  });

  if (!sortedBots.length) return null;

  return (
    <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Moon size={14} color={t.purple} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
          Dreaming by Bot
        </span>
      </div>
      <span style={{ fontSize: 11, color: t.textDim, lineHeight: "17px" }}>
        Toggle dreaming per bot. &ldquo;Inherit&rdquo; uses the global default above.
        Bots without workspace-files memory are shown dimmed.
      </span>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {sortedBots.map((bot) => {
          const current = resolveState(bot.memory_hygiene_enabled);
          const isEligible = bot.memory_scheme === "workspace-files";
          return (
            <div
              key={bot.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                backgroundColor: t.surfaceRaised,
                borderRadius: 8,
                border: `1px solid ${t.surfaceOverlay}`,
                padding: "8px 12px",
                opacity: isEligible ? 1 : 0.45,
              }}
            >
              <button
                onClick={() => router.push(`/admin/bots/${bot.id}#memory` as any)}
                style={{
                  flex: 1, textAlign: "left", cursor: "pointer",
                  background: "none", border: "none", padding: 0,
                }}
              >
                <span style={{ color: t.text, fontSize: 13, fontWeight: 500, display: "block" }}>
                  {bot.name}
                </span>
                {!isEligible && (
                  <span style={{ color: t.textDim, fontSize: 10, display: "block", marginTop: 1 }}>
                    no workspace-files memory
                  </span>
                )}
              </button>

              <div style={{ display: "flex", gap: 4 }}>
                {STATES.map((s) => {
                  const isSelected = current === s;
                  return (
                    <button
                      key={s}
                      disabled={updateMut.isPending || !isEligible}
                      onClick={() => {
                        if (!isSelected && isEligible) {
                          updateMut.mutate({ botId: bot.id, value: stateToValue(s) });
                        }
                      }}
                      style={{
                        padding: "3px 10px",
                        borderRadius: 4,
                        fontSize: 11,
                        fontWeight: 500,
                        cursor: isSelected || !isEligible ? "default" : "pointer",
                        border: isSelected
                          ? `1px solid ${t.purpleBorder}`
                          : `1px solid ${t.surfaceOverlay}`,
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
            </div>
          );
        })}
      </div>
    </div>
  );
}
