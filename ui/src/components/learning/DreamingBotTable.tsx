/**
 * Shared per-bot dreaming table — used by Learning Center > Overview
 * (read-only) and Learning Center > Dreaming (manage mode with toggle + Run).
 *
 * Replaces three near-duplicate copies that lived in OverviewTab, DreamingTab,
 * and the now-deleted DreamingBotList in Settings.
 */
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Moon, Play } from "lucide-react";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useThemeTokens } from "@/src/theme/tokens";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import type { BotDreamingStatus } from "@/src/api/hooks/useLearningOverview";
import type { BotConfig } from "@/src/types/api";
import { useTriggerMemoryHygiene } from "@/src/api/hooks/useMemoryHygiene";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) {
    const mins = Math.floor(-diffMs / 60_000);
    if (mins < 60) return `in ${mins}m`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `in ${hrs}h`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function statusVariant(s: string | null | undefined) {
  if (s === "complete") return "success" as const;
  if (s === "failed") return "danger" as const;
  if (s === "skipped") return "skipped" as const;
  return "neutral" as const;
}

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

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export interface DreamingBotTableProps {
  bots: BotDreamingStatus[];
  /**
   * "view" — Bot / Status / Last Run / Result / Next Run. Click navigates
   *   to the bot's Memory tab.
   * "manage" — adds Toggle (Inherit/On/Off) + Run column. Used in the
   *   canonical Learning Center > Dreaming surface.
   */
  mode: "view" | "manage";
  /** Required in "manage" mode to read each bot's current toggle value. */
  botConfigMap?: Record<string, BotConfig>;
}

export function DreamingBotTable({ bots, mode, botConfigMap }: DreamingBotTableProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { width } = useWindowSize();
  const isMobile = width < 768;
  const qc = useQueryClient();
  const triggerMut = useTriggerMemoryHygiene();

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

  const isManage = mode === "manage";

  // Column widths — keep narrow so the row fits in the dashboard column.
  // Manage mode adds two extra columns (toggle + run).
  const gridTemplate = useMemo(() => {
    if (isManage) {
      // Bot / Status / Last / Result / Next / Toggle / Run
      return "1fr 60px 90px 80px 90px 140px 50px";
    }
    // Bot / Status / Last / Result / Next
    return "1fr 70px 110px 80px 110px";
  }, [isManage]);

  if (bots.length === 0) {
    return (
      <div
        style={{
          padding: 24,
          textAlign: "center",
          borderRadius: 8,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
        }}
      >
        <Moon size={20} color={t.textDim} style={{ marginBottom: 8 }} />
        <div style={{ fontSize: 12, color: t.textDim }}>
          No bots with workspace-files memory. Enable memory on a bot to start dreaming.
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        borderRadius: 8,
        border: `1px solid ${t.surfaceBorder}`,
        overflow: "hidden",
      }}
    >
      {/* Header — desktop only */}
      {!isMobile && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: gridTemplate,
            gap: 8,
            padding: "8px 14px",
            background: t.surfaceOverlay,
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          {(isManage
            ? ["Bot", "Status", "Last Run", "Result", "Next Run", "Dreaming", ""]
            : ["Bot", "Status", "Last Run", "Result", "Next Run"]
          ).map((h, i) => (
            <span
              key={`${h}-${i}`}
              style={{
                fontSize: 9,
                fontWeight: 600,
                color: t.textDim,
                textTransform: "uppercase",
                letterSpacing: 0.5,
              }}
            >
              {h}
            </span>
          ))}
        </div>
      )}

      {/* Rows */}
      {bots.map((bot) => {
        const cfg = botConfigMap?.[bot.bot_id];
        const current = cfg ? resolveState(cfg.memory_hygiene_enabled) : "inherit";

        // Mobile: stacked card layout (works in both modes)
        if (isMobile) {
          return (
            <div
              key={bot.bot_id}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                padding: "10px 14px",
                borderBottom: `1px solid ${t.surfaceBorder}`,
              }}
            >
              <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <button
                  onClick={() => navigate(`/admin/bots/${bot.bot_id}#memory`)}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    color: t.text,
                    fontSize: 13,
                    fontWeight: 500,
                    textAlign: "left",
                  }}
                >
                  {bot.bot_name}
                </button>
                {bot.enabled ? (
                  <StatusBadge label="on" variant="success" />
                ) : (
                  <StatusBadge label="off" variant="neutral" />
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "row", gap: 12, fontSize: 10, color: t.textDim, alignItems: "center" }}>
                <span>Last: {fmtRelative(bot.last_run_at)}</span>
                {bot.last_task_status && (
                  <StatusBadge label={bot.last_task_status} variant={statusVariant(bot.last_task_status)} />
                )}
                <span>Next: {fmtRelative(bot.next_run_at)}</span>
              </div>
              {isManage && (
                <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 }}>
                  <ToggleGroup
                    current={current}
                    disabled={updateMut.isPending}
                    onChange={(s) => updateMut.mutate({ botId: bot.bot_id, value: stateToValue(s) })}
                  />
                  <RunButton
                    enabled={bot.enabled}
                    pending={triggerMut.isPending}
                    onClick={() =>
                      triggerMut.mutate(bot.bot_id, {
                        onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                      })
                    }
                  />
                </div>
              )}
            </div>
          );
        }

        // Desktop: grid row
        return (
          <div
            key={bot.bot_id}
            onClick={() => navigate(`/admin/bots/${bot.bot_id}#memory`)}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = t.inputBg;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
            style={{
              display: "grid",
              gridTemplateColumns: gridTemplate,
              gap: 8,
              padding: "10px 14px",
              background: "transparent",
              borderBottom: `1px solid ${t.surfaceBorder}`,
              cursor: "pointer",
              alignItems: "center",
              transition: "background 0.1s",
            }}
          >
            <span
              style={{
                fontSize: 12,
                fontWeight: 500,
                color: t.text,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {bot.bot_name}
            </span>
            <span>
              {bot.enabled ? (
                <StatusBadge label="on" variant="success" />
              ) : (
                <StatusBadge label="off" variant="neutral" />
              )}
            </span>
            <span style={{ fontSize: 11, color: t.textMuted }}>
              {fmtRelative(bot.last_run_at)}
            </span>
            <span>
              {bot.last_task_status && (
                <StatusBadge label={bot.last_task_status} variant={statusVariant(bot.last_task_status)} />
              )}
            </span>
            <span style={{ fontSize: 11, color: t.textDim }}>
              {fmtRelative(bot.next_run_at)}
            </span>
            {isManage && (
              <>
                <span onClick={(e) => e.stopPropagation()}>
                  <ToggleGroup
                    current={current}
                    disabled={updateMut.isPending}
                    onChange={(s) => updateMut.mutate({ botId: bot.bot_id, value: stateToValue(s) })}
                  />
                </span>
                <span onClick={(e) => e.stopPropagation()}>
                  <RunButton
                    enabled={bot.enabled}
                    pending={triggerMut.isPending}
                    onClick={() =>
                      triggerMut.mutate(bot.bot_id, {
                        onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                      })
                    }
                  />
                </span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal: toggle pills + run button
// ---------------------------------------------------------------------------

function ToggleGroup({
  current,
  disabled,
  onChange,
}: {
  current: HygieneState;
  disabled: boolean;
  onChange: (s: HygieneState) => void;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 4 }}>
      {STATES.map((s) => {
        const isSelected = current === s;
        return (
          <button
            key={s}
            disabled={disabled || isSelected}
            onClick={() => {
              if (!isSelected) onChange(s);
            }}
            style={{
              padding: "3px 8px",
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 500,
              cursor: isSelected ? "default" : "pointer",
              border: isSelected
                ? `1px solid ${t.purpleBorder}`
                : `1px solid ${t.surfaceOverlay}`,
              background: isSelected ? t.purpleSubtle : "transparent",
              color: isSelected ? t.purple : t.textDim,
              opacity: disabled ? 0.6 : 1,
              textTransform: "capitalize",
            }}
          >
            {s}
          </button>
        );
      })}
    </div>
  );
}

function RunButton({
  enabled,
  pending,
  onClick,
}: {
  enabled: boolean;
  pending: boolean;
  onClick: () => void;
}) {
  const t = useThemeTokens();
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        if (enabled) onClick();
      }}
      disabled={!enabled || pending}
      title={enabled ? "Trigger dreaming run now" : "Dreaming is disabled for this bot"}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        gap: 4,
        padding: "4px 8px",
        borderRadius: 4,
        fontSize: 10,
        fontWeight: 500,
        background: enabled ? t.purpleSubtle : "transparent",
        color: enabled ? t.purple : t.textDim,
        border: `1px solid ${enabled ? t.purpleBorder : t.surfaceOverlay}`,
        cursor: enabled ? "pointer" : "not-allowed",
        opacity: pending ? 0.6 : 1,
      }}
    >
      <Play size={10} />
    </button>
  );
}
