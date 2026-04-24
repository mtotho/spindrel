/**
 * Shared per-bot dreaming control list, used by Memory & Knowledge > Dreaming
 * and the global Memory & Learning settings surface.
 */
import { Moon, Play } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/src/api/client";
import type { BotDreamingStatus } from "@/src/api/hooks/useLearningOverview";
import { useTriggerMemoryHygiene } from "@/src/api/hooks/useMemoryHygiene";
import { cn } from "@/src/lib/cn";
import type { BotConfig } from "@/src/types/api";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
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
  if (s === "running") return "info" as const;
  return "neutral" as const;
}

type HygieneState = "inherit" | "on" | "off";
type JobFlavor = "maintenance" | "skills";

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

const JOB_STYLE = {
  maintenance: {
    label: "Maintenance",
    shortLabel: "maint",
    dot: "bg-warning",
    dimDot: "bg-warning/20",
    panel: "bg-warning/[0.07]",
    text: "text-warning-muted",
    ring: "focus-visible:ring-warning/35",
    field: "memory_hygiene_enabled",
    jobType: "memory_hygiene",
  },
  skills: {
    label: "Skill Review",
    shortLabel: "skills",
    dot: "bg-purple",
    dimDot: "bg-purple/20",
    panel: "bg-purple/[0.07]",
    text: "text-purple",
    ring: "focus-visible:ring-purple/35",
    field: "skill_review_enabled",
    jobType: "skill_review",
  },
} as const;

export interface DreamingBotTableProps {
  bots: BotDreamingStatus[];
  mode: "view" | "manage";
  botConfigMap?: Record<string, BotConfig>;
}

export function DreamingBotTable({ bots, mode, botConfigMap }: DreamingBotTableProps) {
  const navigate = useNavigate();
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
      {bots.map((bot) => {
        const cfg = botConfigMap?.[bot.bot_id];
        const maintenanceState = cfg ? resolveState(cfg.memory_hygiene_enabled) : "inherit";
        const skillsState = cfg ? resolveState(cfg.skill_review_enabled) : "inherit";

        return (
          <div key={bot.bot_id} className="rounded-md bg-surface-raised/40 px-3 py-2.5">
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <button
                type="button"
                onClick={() => navigate(`/admin/bots/${bot.bot_id}#memory`)}
                className="min-w-0 bg-transparent p-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-[13px] font-semibold text-text transition-colors hover:text-accent">
                    {bot.bot_name}
                  </span>
                  <JobDot enabled={bot.enabled} flavor="maintenance" />
                  <JobDot enabled={bot.skill_review_enabled} flavor="skills" />
                </div>
                <div className="mt-0.5 text-[11px] text-text-dim">
                  Workspace-files memory background jobs
                </div>
              </button>
              <div className="flex flex-wrap items-center gap-1.5">
                <QuietPill
                  label={`${bot.enabled ? "maint on" : "maint off"}`}
                  className={bot.enabled ? "bg-warning/10 text-warning-muted" : ""}
                  maxWidthClass="max-w-none"
                />
                <QuietPill
                  label={`${bot.skill_review_enabled ? "skills on" : "skills off"}`}
                  className={bot.skill_review_enabled ? "bg-purple/10 text-purple" : ""}
                  maxWidthClass="max-w-none"
                />
              </div>
            </div>

            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              <DreamingJobLane
                flavor="maintenance"
                enabled={bot.enabled}
                state={maintenanceState}
                lastRunAt={bot.last_run_at}
                nextRunAt={bot.next_run_at}
                lastStatus={bot.last_task_status}
                mode={mode}
                pending={updateMut.isPending || triggerMut.isPending}
                onCycle={() =>
                  updateMut.mutate({
                    botId: bot.bot_id,
                    field: JOB_STYLE.maintenance.field,
                    value: stateToValue(nextState(maintenanceState)),
                  })
                }
                onRun={() =>
                  triggerMut.mutate({ botId: bot.bot_id, jobType: JOB_STYLE.maintenance.jobType }, {
                    onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                  })
                }
              />
              <DreamingJobLane
                flavor="skills"
                enabled={bot.skill_review_enabled}
                state={skillsState}
                lastRunAt={bot.skill_review_last_run_at}
                nextRunAt={bot.skill_review_next_run_at}
                lastStatus={bot.skill_review_last_task_status}
                mode={mode}
                pending={updateMut.isPending || triggerMut.isPending}
                onCycle={() =>
                  updateMut.mutate({
                    botId: bot.bot_id,
                    field: JOB_STYLE.skills.field,
                    value: stateToValue(nextState(skillsState)),
                  })
                }
                onRun={() =>
                  triggerMut.mutate({ botId: bot.bot_id, jobType: JOB_STYLE.skills.jobType }, {
                    onSuccess: () => qc.invalidateQueries({ queryKey: ["learning-overview"] }),
                  })
                }
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DreamingJobLane({
  flavor,
  enabled,
  state,
  lastRunAt,
  nextRunAt,
  lastStatus,
  mode,
  pending,
  onCycle,
  onRun,
}: {
  flavor: JobFlavor;
  enabled: boolean;
  state: HygieneState;
  lastRunAt?: string | null;
  nextRunAt?: string | null;
  lastStatus?: string | null;
  mode: "view" | "manage";
  pending: boolean;
  onCycle: () => void;
  onRun: () => void;
}) {
  const style = JOB_STYLE[flavor];
  return (
    <div className={cn("rounded-md px-3 py-2.5", style.panel)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <JobDot enabled={enabled} flavor={flavor} />
          <span className={cn("text-[12px] font-semibold", style.text)}>
            {style.label}
          </span>
          <StatusBadge label={enabled ? "enabled" : "off"} variant={enabled ? (flavor === "skills" ? "purple" : "warning") : "neutral"} />
        </div>
        {mode === "manage" && (
          <div className="flex items-center gap-1.5">
            <StateToggle
              state={state}
              flavor={flavor}
              disabled={pending}
              onClick={onCycle}
            />
            <ActionButton
              label="Run"
              size="small"
              variant="secondary"
              disabled={!enabled || pending}
              icon={<Play size={11} />}
              onPress={onRun}
            />
          </div>
        )}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
        <Metric label="Last" value={fmtRelative(lastRunAt)} />
        <Metric
          label="Result"
          value={lastStatus ? <StatusBadge label={lastStatus} variant={statusVariant(lastStatus)} /> : "none"}
        />
        <Metric label="Next" value={fmtRelative(nextRunAt)} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {label}
      </div>
      <div className="mt-0.5 min-h-[18px] truncate text-text-muted">{value}</div>
    </div>
  );
}

function JobDot({ enabled, flavor }: { enabled: boolean; flavor: JobFlavor }) {
  const style = JOB_STYLE[flavor];
  return (
    <span
      title={`${style.label}: ${enabled ? "on" : "off"}`}
      className={cn("inline-block size-2 rounded-full", enabled ? style.dot : style.dimDot)}
    />
  );
}

function StateToggle({
  state,
  flavor,
  disabled,
  onClick,
}: {
  state: HygieneState;
  flavor: JobFlavor;
  disabled: boolean;
  onClick: () => void;
}) {
  const style = JOB_STYLE[flavor];
  const title = `${style.label}: ${state} - click to cycle`;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2 text-[11px] font-semibold transition-colors",
        "focus:outline-none focus-visible:ring-2",
        style.ring,
        disabled ? "cursor-default opacity-50" : "hover:bg-surface-overlay/45",
        state === "off" ? "text-text-dim" : style.text,
      )}
    >
      <span
        className={cn(
          "inline-block size-2 rounded-full",
          state === "off" ? "bg-surface-overlay" : style.dot,
        )}
      />
      {state}
    </button>
  );
}
