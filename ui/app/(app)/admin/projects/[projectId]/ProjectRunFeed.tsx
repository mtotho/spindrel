import { Link } from "react-router-dom";
import { CalendarClock, CheckCircle2, GitBranch, GitMerge } from "lucide-react";

import type { ProjectCodingRunSchedule } from "@/src/types/api";
import { EmptyState, StatusBadge } from "@/src/components/shared/SettingsControls";
import { formatRunTime } from "./ProjectRunControls";
import { evidenceLine, type FeedItem, isActiveRun, isClosedRun, itemTimestamp, reviewStatus, runStatus, runTitle, startedTimestamp } from "./ProjectRunsModel";

function runTone(run: FeedItem & { kind: "run" }): "success" | "warning" | "danger" | "neutral" {
  const status = runStatus(run.run);
  const review = reviewStatus(run.run);
  if (review === "blocked" || review === "changes_requested" || status === "failed") return "danger";
  if (isActiveRun(run.run) || review === "ready_for_review" || review === "needs_review") return "warning";
  if (isClosedRun(run.run)) return "success";
  return "neutral";
}

function scheduleMeta(schedule: ProjectCodingRunSchedule) {
  const pieces = [
    schedule.enabled ? "active" : "paused",
    schedule.recurrence || "manual",
    schedule.scheduled_at ? `next ${formatRunTime(schedule.scheduled_at)}` : "no next time",
    `${schedule.run_count} run${schedule.run_count === 1 ? "" : "s"}`,
  ];
  return pieces.join(" · ");
}

function RunFeedRow({
  item,
  projectId,
  onSelectSchedule,
}: {
  item: FeedItem;
  projectId: string;
  onSelectSchedule: (schedule: ProjectCodingRunSchedule) => void;
}) {
  if (item.kind === "schedule") {
    const schedule = item.schedule;
    return (
      <button
        type="button"
        onClick={() => onSelectSchedule(schedule)}
        className="grid w-full grid-cols-[minmax(132px,0.24fr)_minmax(0,1fr)_auto] items-center gap-3 rounded-md bg-surface-raised/35 px-3 py-2 text-left transition-colors hover:bg-surface-overlay/40"
      >
        <div className="flex min-w-0 items-center gap-2 text-[12px] text-text-muted">
          <CalendarClock size={14} className="shrink-0 text-text-dim" />
          <span className="truncate">{schedule.scheduled_at ? formatRunTime(schedule.scheduled_at) : "Manual"}</span>
        </div>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-text">{schedule.title}</div>
          <div className="truncate text-[11px] text-text-muted">{scheduleMeta(schedule)}</div>
        </div>
        <StatusBadge label={schedule.enabled ? "upcoming" : "paused"} variant={schedule.enabled ? "info" : "neutral"} />
      </button>
    );
  }

  const run = item.run;
  const review = reviewStatus(run);
  const status = review || runStatus(run);
  const active = isActiveRun(run);
  const Icon = item.group === "history" ? CheckCircle2 : review.includes("review") ? GitMerge : GitBranch;
  return (
    <Link
      to={`/admin/projects/${projectId}/runs/${run.task.id}`}
      className="grid w-full grid-cols-[minmax(132px,0.24fr)_minmax(0,1fr)_auto] items-center gap-3 rounded-md bg-surface-raised/35 px-3 py-2 text-left no-underline transition-colors hover:bg-surface-overlay/40"
    >
      <div className="flex min-w-0 items-center gap-2 text-[12px] text-text-muted">
        <Icon size={14} className="shrink-0 text-text-dim" />
        <span className="truncate">{formatRunTime(itemTimestamp(run) || startedTimestamp(run))}</span>
      </div>
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold text-text">{runTitle(run)}</div>
        <div className="truncate text-[11px] text-text-muted">
          {[active ? "running" : status.replaceAll("_", " "), run.branch ? `branch ${run.branch}` : null, run.task.session_id ? "session" : "no session", evidenceLine(run)].filter(Boolean).join(" · ")}
        </div>
      </div>
      <StatusBadge label={status.replaceAll("_", " ") || "run"} variant={runTone(item)} />
    </Link>
  );
}

export function ProjectRunFeed({
  items,
  projectId,
  onSelectSchedule,
}: {
  items: FeedItem[];
  projectId: string;
  onSelectSchedule: (schedule: ProjectCodingRunSchedule) => void;
}) {
  if (items.length === 0) {
    return (
      <div data-testid="project-workspace-feed" className="px-3 py-3">
        <EmptyState message="No Project runs or schedules are available yet." />
      </div>
    );
  }

  return (
    <div data-testid="project-workspace-feed" className="flex min-h-full flex-col gap-1.5 px-3 py-3">
      <div className="flex items-center gap-2 px-1 pb-1 text-[10px] font-bold uppercase tracking-[0.08em] text-text-dim/80">
        <span>Chronological</span>
        <span className="text-text-dim">{items.length}</span>
      </div>
      {items.map((item) => (
        <RunFeedRow key={item.id} item={item} projectId={projectId} onSelectSchedule={onSelectSchedule} />
      ))}
    </div>
  );
}
