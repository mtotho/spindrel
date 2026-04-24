/**
 * Shared per-bot dreaming table — used by Memory & Knowledge > Dreaming
 * and the global Memory & Learning settings surface.
 *
 * Displays dual job types: Memory Maintenance (amber) and Skill Review (purple).
 */
import { useMemo, useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Moon, Play, ChevronDown } from "lucide-react";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { cn } from "@/src/lib/cn";
import {
  EmptyState,
  QuietPill,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
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
   *   canonical Memory & Knowledge > Dreaming surface.
   */
  mode: "view" | "manage";
  /** Required in "manage" mode to read each bot's current toggle value. */
  botConfigMap?: Record<string, BotConfig>;
}

export function DreamingBotTable({ bots, mode, botConfigMap }: DreamingBotTableProps) {
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
      <EmptyState
        message={
          <div className="flex flex-col items-center gap-2 text-center">
            <Moon size={18} className="text-text-dim" />
            <span>
          No bots with workspace-files memory. Enable memory on a bot to start dreaming.
            </span>
          </div>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Header — desktop only */}
      {!isMobile && (
        <div
          className="grid items-center gap-2 rounded-md bg-surface-overlay/35 px-3 py-2"
          style={{
            gridTemplateColumns: gridTemplate,
          }}
        >
          {(isManage
            ? ["Bot", "Last Run", "Result", "Next Run", "Maint", "Skills", ""]
            : ["Bot", "Jobs", "Last Run", "Result", "Next Run"]
          ).map((h, i) => (
            <span
              key={`${h}-${i}`}
              className={cn(
                "text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70",
                isManage && (i === 4 || i === 5) && "text-center",
              )}
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
        // Track which job type ran last / runs next
        const lastRun = (() => {
          if (!bot.last_run_at && !bot.skill_review_last_run_at) return { at: null, type: null as string | null };
          if (!bot.last_run_at) return { at: bot.skill_review_last_run_at, type: "skills" };
          if (!bot.skill_review_last_run_at) return { at: bot.last_run_at, type: "maint" };
          return new Date(bot.last_run_at) > new Date(bot.skill_review_last_run_at)
            ? { at: bot.last_run_at, type: "maint" } : { at: bot.skill_review_last_run_at, type: "skills" };
        })();
        const nextRun = (() => {
          if (!bot.next_run_at && !bot.skill_review_next_run_at) return { at: null, type: null as string | null };
          if (!bot.next_run_at) return { at: bot.skill_review_next_run_at, type: "skills" };
          if (!bot.skill_review_next_run_at) return { at: bot.next_run_at, type: "maint" };
          return new Date(bot.next_run_at) < new Date(bot.skill_review_next_run_at)
            ? { at: bot.next_run_at, type: "maint" } : { at: bot.skill_review_next_run_at, type: "skills" };
        })();

        // Mobile: stacked card layout
        if (isMobile) {
          return (
            <div
              key={bot.bot_id}
              className="flex flex-col gap-2 rounded-md bg-surface-raised/40 px-3 py-2.5"
            >
              <div className="flex items-center justify-between gap-3">
                <button
                  onClick={() => navigate(`/admin/bots/${bot.bot_id}#memory`)}
                  className="min-w-0 truncate bg-transparent p-0 text-left text-[13px] font-semibold text-text transition-colors hover:text-accent"
                >
                  {bot.bot_name}
                </button>
                <div className="flex items-center gap-2">
                  <DotIndicator enabled={bot.enabled} flavor="maint" />
                  <DotIndicator enabled={bot.skill_review_enabled} flavor="skills" />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-dim">
                <span>Last: {fmtRelative(lastRun.at)}{lastRun.type && <TypeDot type={lastRun.type} />}</span>
                {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                <span>Next: {fmtRelative(nextRun.at)}{nextRun.type && <TypeDot type={nextRun.type} />}</span>
              </div>
              {isManage && (
                <div className="mt-1 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
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
            className="grid cursor-pointer items-center gap-2 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45 focus-within:ring-2 focus-within:ring-accent/35"
            style={{
              gridTemplateColumns: gridTemplate,
            }}
          >
            <span className="truncate text-[12px] font-semibold text-text">
              {bot.bot_name}
            </span>

            {isManage ? (
              <>
                {/* Last Run */}
                <span className="text-[11px] text-text-muted">
                  {fmtRelative(lastRun.at)}{lastRun.type && <TypeDot type={lastRun.type} />}
                </span>
                {/* Result */}
                <span>
                  {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                </span>
                {/* Next Run */}
                <span className="text-[11px] text-text-dim">
                  {fmtRelative(nextRun.at)}{nextRun.type && <TypeDot type={nextRun.type} />}
                </span>
                {/* Maint dot toggle */}
                <span
                  onClick={(e) => e.stopPropagation()}
                  className="flex justify-center"
                >
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
                <span
                  onClick={(e) => e.stopPropagation()}
                  className="flex justify-center"
                >
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
                <span className="flex items-center gap-2">
                  <DotIndicator enabled={bot.enabled} flavor="maint" />
                  <DotIndicator enabled={bot.skill_review_enabled} flavor="skills" />
                </span>
                {/* Last Run */}
                <span className="text-[11px] text-text-muted">
                  {fmtRelative(lastRun.at)}{lastRun.type && <TypeDot type={lastRun.type} />}
                </span>
                {/* Result — worst-of-two */}
                <span>
                  {combined && <StatusBadge label={combined} variant={statusVariant(combined)} />}
                </span>
                {/* Next Run */}
                <span className="text-[11px] text-text-dim">
                  {fmtRelative(nextRun.at)}{nextRun.type && <TypeDot type={nextRun.type} />}
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

/** Tiny inline color dot showing which job type a timestamp refers to */
function TypeDot({ type }: { type: string }) {
  return (
    <span
      title={type === "maint" ? "Maintenance" : "Skill Review"}
      className={cn(
        "ml-1 inline-block size-1.5 rounded-full align-middle",
        type === "maint" ? "bg-warning" : "bg-purple",
      )}
    />
  );
}

function DotIndicator({ enabled, flavor }: { enabled: boolean; flavor: "maint" | "skills" }) {
  return (
    <span
      title={`${flavor === "maint" ? "Maintenance" : "Skill Review"}: ${enabled ? "on" : "off"}`}
      className={cn(
        "inline-block size-2 rounded-full",
        flavor === "maint"
          ? enabled ? "bg-warning" : "bg-warning/20"
          : enabled ? "bg-purple" : "bg-purple/20",
      )}
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
  const title = `${label}: ${state} — click to cycle`;
  const isMaintenance = flavor === "maint";

  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      disabled={disabled}
      title={title}
      className={cn(
        "relative inline-flex size-[22px] items-center justify-center rounded-full border p-0 transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
        disabled ? "cursor-default opacity-50" : "cursor-pointer",
        isMaintenance
          ? state === "on"
            ? "border-warning/40 bg-warning text-surface"
            : state === "inherit"
              ? "border-warning/40 bg-warning/20 text-warning-muted"
              : "border-warning/40 bg-transparent text-warning-muted"
          : state === "on"
            ? "border-purple/40 bg-purple text-surface"
            : state === "inherit"
              ? "border-purple/40 bg-purple/20 text-purple"
              : "border-purple/40 bg-transparent text-purple",
      )}
    >
      {/* Inner dot for "on" */}
      {state === "on" && (
        <span className="block size-2 rounded-full bg-surface-raised" />
      )}
      {/* Dash for "off" */}
      {state === "off" && (
        <span className="block h-0.5 w-1.5 rounded-full bg-current" />
      )}
      {/* Half-circle for "inherit" */}
      {state === "inherit" && (
        <span className="block size-2 rounded-full bg-current [clip-path:inset(0_50%_0_0)]" />
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
        title={anyEnabled ? "Choose which job to run" : "No jobs enabled for this bot"}
        className={cn(
          "inline-flex min-h-[30px] items-center justify-center gap-1 rounded-md px-2 text-[11px] font-semibold transition-colors",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
          anyEnabled
            ? "bg-transparent text-accent hover:bg-accent/[0.08]"
            : "cursor-default bg-transparent text-text-dim",
          pending && "opacity-50",
        )}
      >
        <Play size={10} />
        <ChevronDown size={8} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-[80] mt-1 flex min-w-[180px] flex-col gap-1 rounded-md border border-surface-border bg-surface-raised p-1">
          <RunMenuItem
            enabled={maintEnabled}
            pending={pending}
            flavor="maint"
            label="Run Maintenance"
            onClick={() => { onTrigger("memory_hygiene"); setOpen(false); }}
          />
          <RunMenuItem
            enabled={skillsEnabled}
            pending={pending}
            flavor="skills"
            label="Run Skill Review"
            onClick={() => { onTrigger("skill_review"); setOpen(false); }}
          />
        </div>
      )}
    </div>
  );
}

function RunMenuItem({
  enabled,
  pending,
  flavor,
  label,
  onClick,
}: {
  enabled: boolean;
  pending: boolean;
  flavor: "maint" | "skills";
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={!enabled || pending}
      onClick={onClick}
      className={cn(
        "flex min-h-[34px] w-full items-center gap-2 rounded-md px-2.5 text-left text-[12px] font-medium text-text transition-colors",
        "hover:bg-surface-overlay/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
        (!enabled || pending) && "cursor-default opacity-45 hover:bg-transparent",
      )}
    >
      <span
        className={cn(
          "inline-block size-2 rounded-full",
          flavor === "maint" ? "bg-warning" : "bg-purple",
        )}
      />
      <span>{label}</span>
      <QuietPill
        label={flavor === "maint" ? "maintenance" : "skills"}
        className={flavor === "maint" ? "ml-auto bg-warning/10 text-warning-muted" : "ml-auto bg-purple/10 text-purple"}
        maxWidthClass="max-w-none"
      />
    </button>
  );
}
