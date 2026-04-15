/**
 * Shared per-bot dreaming table — used by Learning Center > Overview
 * (read-only) and Learning Center > Dreaming (manage mode with toggle + Run).
 *
 * Displays dual job types: Memory Maintenance (amber) and Skill Review (purple).
 */
import { useMemo, useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Moon, Play, ChevronDown } from "lucide-react";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useThemeTokens } from "@/src/theme/tokens";
import { StatusBadge } from "@/src/components/shared/SettingsControls";
import type { BotDreamingStatus } from "@/src/api/hooks/useLearningOverview";
import type { BotConfig } from "@/src/types/api";
import type { HygieneJobType } from "@/src/api/hooks/useMemoryHygiene";
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

/** Worst-of-two: failed > skipped > neutral > complete */
function worstStatus(a: string | null | undefined, b: string | null | undefined): string | null {
  const priority: Record<string, number> = { failed: 3, skipped: 2, running: 1, complete: 0 };
  const pa = a ? (priority[a] ?? 1) : -1;
  const pb = b ? (priority[b] ?? 1) : -1;
  if (pa >= pb) return a ?? null;
  return b ?? null;
}

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

function nextState(current: HygieneState): HygieneState {
  if (current === "on") return "off";
  if (current === "off") return "inherit";
  return "on";
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export interface DreamingBotTableProps {
  bots: BotDreamingStatus[];
  /**
   * "view" — Bot / Jobs / Last Run / Result / Next Run. Click navigates
   *   to the bot's Memory tab.
   * "manage" — adds Maint + Skills dot toggles + Run dropdown. Used in the
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
    mutationFn: ({ botId, field, value }: { botId: string; field: string; value: boolean | null }) =>
      apiFetch<BotConfig>(`/api/v1/admin/bots/${botId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: value }),
      }),
    onSuccess: (_data, { botId }) => {
      qc.invalidateQueries({ queryKey: ["bots", botId] });
      qc.invalidateQueries({ queryKey: ["admin-bots"] });
      qc.invalidateQueries({ queryKey: ["learning-overview"] });
    },
  });

  const isManage = mode === "manage";

  const gridTemplate = useMemo(() => {
    if (isManage) {
      // Bot / Last Run / Result / Next / Maint dot / Skills dot / Run
      return "1fr 90px 80px 90px 56px 56px 58px";
    }
    // Bot / Jobs / Last Run / Result / Next
    return "1fr 80px 110px 80px 110px";
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
            ? ["Bot", "Last Run", "Result", "Next Run", "Maint", "Skills", ""]
            : ["Bot", "Jobs", "Last Run", "Result", "Next Run"]
          ).map((h, i) => (
            <span
              key={`${h}-${i}`}
              style={{
                fontSize: 9,
                fontWeight: 600,
                color: t.textDim,
                textTransform: "uppercase",
                letterSpacing: 0.5,
                textAlign: (isManage && (i === 4 || i === 5)) ? "center" : undefined,
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
        const maintState = cfg ? resolveState(cfg.memory_hygiene_enabled) : "inherit";
        const skillState = cfg ? resolveState(cfg.skill_review_enabled) : "inherit";
        const combined = worstStatus(bot.last_task_status, bot.skill_review_last_task_status);
        const lastRunAt = (() => {
          if (!bot.last_run_at && !bot.skill_review_last_run_at) return null;
          if (!bot.last_run_at) return bot.skill_review_last_run_at;
          if (!bot.skill_review_last_run_at) return bot.last_run_at;
          return new Date(bot.last_run_at) > new Date(bot.skill_review_last_run_at)
            ? bot.last_run_at : bot.skill_review_last_run_at;
        })();
        const nextRunAt = (() => {
          if (!bot.next_run_at && !bot.skill_review_next_run_at) return null;
          if (!bot.next_run_at) return bot.skill_review_next_run_at;
          if (!bot.skill_review_next_run_at) return bot.next_run_at;
          return new Date(bot.next_run_at) < new Date(bot.skill_review_next_run_at)
            ? bot.next_run_at : bot.skill_review_next_run_at;
        })();

        // Mobile: stacked card layout
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
              <div className="flex items-center justify-between">
                <button
                  onClick={() => navigate(`/admin/bots/${bot.bot_id}#memory`)}
                  className="bg-transparent border-none p-0 cursor-pointer text-left"
                  style={{ color: t.text, fontSize: 13, fontWeight: 500 }}
                >
                  {bot.bot_name}
                </button>
                <div className="flex items-center gap-1.5">
                  <DotIndicator enabled={bot.enabled} flavor="maint" />
                  <DotIndicator enabled={bot.skill_review_enabled} flavor="skills" />
                </div>
              </div>
              <div className="flex items-center gap-3" style={{ fontSize: 10, color: t.textDim }}>
                <span>Last: {fmtRelative(lastRunAt)}</span>
                {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                <span>Next: {fmtRelative(nextRunAt)}</span>
              </div>
              {isManage && (
                <div className="flex items-center gap-3 mt-1">
                  <div className="flex items-center gap-1.5">
                    <DotToggle
                      state={maintState}
                      flavor="maint"
                      disabled={updateMut.isPending}
                      onClick={() => updateMut.mutate({
                        botId: bot.bot_id,
                        field: "memory_hygiene_enabled",
                        value: stateToValue(nextState(maintState)),
                      })}
                    />
                    <DotToggle
                      state={skillState}
                      flavor="skills"
                      disabled={updateMut.isPending}
                      onClick={() => updateMut.mutate({
                        botId: bot.bot_id,
                        field: "skill_review_enabled",
                        value: stateToValue(nextState(skillState)),
                      })}
                    />
                  </div>
                  <RunDropdown
                    maintEnabled={bot.enabled}
                    skillsEnabled={bot.skill_review_enabled}
                    pending={triggerMut.isPending}
                    onTrigger={(jobType) =>
                      triggerMut.mutate({ botId: bot.bot_id, jobType }, {
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

            {isManage ? (
              <>
                {/* Last Run */}
                <span style={{ fontSize: 11, color: t.textMuted }}>
                  {fmtRelative(lastRunAt)}
                </span>
                {/* Result */}
                <span>
                  {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                </span>
                {/* Next Run */}
                <span style={{ fontSize: 11, color: t.textDim }}>
                  {fmtRelative(nextRunAt)}
                </span>
                {/* Maint dot toggle */}
                <span className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                  <DotToggle
                    state={maintState}
                    flavor="maint"
                    disabled={updateMut.isPending}
                    onClick={() => updateMut.mutate({
                      botId: bot.bot_id,
                      field: "memory_hygiene_enabled",
                      value: stateToValue(nextState(maintState)),
                    })}
                  />
                </span>
                {/* Skills dot toggle */}
                <span className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                  <DotToggle
                    state={skillState}
                    flavor="skills"
                    disabled={updateMut.isPending}
                    onClick={() => updateMut.mutate({
                      botId: bot.bot_id,
                      field: "skill_review_enabled",
                      value: stateToValue(nextState(skillState)),
                    })}
                  />
                </span>
                {/* Run dropdown */}
                <span onClick={(e) => e.stopPropagation()}>
                  <RunDropdown
                    maintEnabled={bot.enabled}
                    skillsEnabled={bot.skill_review_enabled}
                    pending={triggerMut.isPending}
                    onTrigger={(jobType) =>
                      triggerMut.mutate({ botId: bot.bot_id, jobType }, {
                        onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                      })
                    }
                  />
                </span>
              </>
            ) : (
              <>
                {/* Jobs — dual dot indicators */}
                <span className="flex items-center gap-1.5">
                  <DotIndicator enabled={bot.enabled} flavor="maint" />
                  <DotIndicator enabled={bot.skill_review_enabled} flavor="skills" />
                </span>
                {/* Last Run */}
                <span style={{ fontSize: 11, color: t.textMuted }}>
                  {fmtRelative(lastRunAt)}
                </span>
                {/* Result — worst-of-two */}
                <span>
                  {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                </span>
                {/* Next Run */}
                <span style={{ fontSize: 11, color: t.textDim }}>
                  {fmtRelative(nextRunAt)}
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
// Internal: Dot indicator (view mode — read-only)
// ---------------------------------------------------------------------------

function DotIndicator({ enabled, flavor }: { enabled: boolean; flavor: "maint" | "skills" }) {
  const colorClass = flavor === "maint"
    ? (enabled ? "bg-amber-500" : "bg-amber-500/20")
    : (enabled ? "bg-purple-500" : "bg-purple-500/20");
  const title = `${flavor === "maint" ? "Maintenance" : "Skill Review"}: ${enabled ? "on" : "off"}`;

  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colorClass}`}
      title={title}
    />
  );
}

// ---------------------------------------------------------------------------
// Internal: Dot toggle (manage mode — clickable state cycle)
// ---------------------------------------------------------------------------

function DotToggle({
  state,
  flavor,
  disabled,
  onClick,
}: {
  state: HygieneState;
  flavor: "maint" | "skills";
  disabled: boolean;
  onClick: () => void;
}) {
  const label = flavor === "maint" ? "Maintenance" : "Skill Review";
  const title = `${label}: ${state}${state === "inherit" ? " (click to change)" : ""} — click to cycle`;

  // On = solid, Off = ring only, Inherit = half-opacity solid
  // Static class names (no template literals — Tailwind JIT requires them)
  const dotClass = (() => {
    if (flavor === "maint") {
      if (state === "on") return "bg-amber-500 ring-1 ring-amber-500/30";
      if (state === "off") return "bg-transparent ring-1 ring-amber-500/40";
      return "bg-amber-500/40 ring-1 ring-amber-500/30";
    }
    if (state === "on") return "bg-purple-500 ring-1 ring-purple-500/30";
    if (state === "off") return "bg-transparent ring-1 ring-purple-500/40";
    return "bg-purple-500/40 ring-1 ring-purple-500/30";
  })();

  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      disabled={disabled}
      title={title}
      className={`
        relative w-5 h-5 rounded-full cursor-pointer
        flex items-center justify-center
        transition-all duration-150
        disabled:opacity-50 disabled:cursor-not-allowed
        hover:scale-110
        ${dotClass}
      `}
      style={{ border: "none" }}
    >
      {/* Inner dot for "on" state emphasis */}
      {state === "on" && (
        <span className={`block w-2 h-2 rounded-full ${
          flavor === "maint" ? "bg-amber-300" : "bg-purple-300"
        }`} />
      )}
      {/* Dash for "off" */}
      {state === "off" && (
        <span className={`block w-1.5 h-px ${
          flavor === "maint" ? "bg-amber-500/50" : "bg-purple-500/50"
        }`} />
      )}
      {/* Half-circle for "inherit" */}
      {state === "inherit" && (
        <span className={`block w-2 h-2 rounded-full clip-half ${
          flavor === "maint" ? "bg-amber-500/70" : "bg-purple-500/70"
        }`} />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Internal: Run dropdown (manage mode)
// ---------------------------------------------------------------------------

function RunDropdown({
  maintEnabled,
  skillsEnabled,
  pending,
  onTrigger,
}: {
  maintEnabled: boolean;
  skillsEnabled: boolean;
  pending: boolean;
  onTrigger: (jobType: HygieneJobType) => void;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const anyEnabled = maintEnabled || skillsEnabled;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (anyEnabled) setOpen(!open);
        }}
        disabled={!anyEnabled || pending}
        title={anyEnabled ? "Trigger a dreaming run" : "No jobs enabled for this bot"}
        style={{
          display: "inline-flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 2,
          padding: "4px 6px",
          borderRadius: 4,
          fontSize: 10,
          fontWeight: 500,
          cursor: anyEnabled ? "pointer" : "not-allowed",
          opacity: pending ? 0.5 : 1,
          background: anyEnabled ? t.purpleSubtle : "transparent",
          color: anyEnabled ? t.purple : t.textDim,
          border: `1px solid ${anyEnabled ? t.purpleBorder : t.surfaceOverlay}`,
        }}
      >
        <Play size={10} />
        <ChevronDown size={8} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 rounded-md overflow-hidden shadow-lg"
          style={{
            minWidth: 160,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <button
            disabled={!maintEnabled || pending}
            onClick={() => { onTrigger("memory_hygiene"); setOpen(false); }}
            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2
              disabled:opacity-40 disabled:cursor-not-allowed
              hover:bg-white/5 transition-colors cursor-pointer"
            style={{ color: t.text, background: "transparent", border: "none" }}
          >
            <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
            Run Maintenance
          </button>
          <button
            disabled={!skillsEnabled || pending}
            onClick={() => { onTrigger("skill_review"); setOpen(false); }}
            className="w-full text-left px-3 py-2 text-xs flex items-center gap-2
              disabled:opacity-40 disabled:cursor-not-allowed
              hover:bg-white/5 transition-colors cursor-pointer"
            style={{ color: t.text, background: "transparent", border: "none" }}
          >
            <span className="inline-block w-2 h-2 rounded-full bg-purple-500" />
            Run Skill Review
          </button>
        </div>
      )}
    </div>
  );
}
