import { CalendarClock, CheckCircle2, FileText, GitBranch, GitMerge, Play } from "lucide-react";
import type { ReactNode } from "react";

import type { ProjectCodingRun, ProjectCodingRunReviewBatch, ProjectCodingRunSchedule } from "@/src/types/api";
import { formatRunTime } from "./ProjectRunControls";
import {
  type BoardItem,
  evidenceLine,
  isActiveRun,
  isClosedRun,
  isStaleActive,
  itemTimestamp,
  reviewStatus,
  runStatus,
  runTitle,
  shortId,
  startedTimestamp,
} from "./ProjectRunsModel";

export function compactAge(value?: string | null) {
  if (!value) return "now";
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return "now";
  const ms = Math.max(0, Date.now() - time);
  if (ms <= 0) return "now";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (hours < 48) return remaining ? `${hours}h ${remaining}m` : `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

export function runMetaLine(run: ProjectCodingRun) {
  const pieces = [
    startedTimestamp(run) ? `started ${formatRunTime(startedTimestamp(run))}` : null,
    run.branch ? `branch ${run.branch}` : null,
    run.repo?.path ? String(run.repo.path) : null,
  ].filter(Boolean);
  return pieces.join(" · ") || "Project coding run";
}

export function batchTitle(batch: ProjectCodingRunReviewBatch) {
  return batch.summary?.title || `Launch batch ${shortId(batch.id)}`;
}

export function scheduleNextLine(schedule: ProjectCodingRunSchedule) {
  const next = schedule.scheduled_at ? `next ${formatRunTime(schedule.scheduled_at)}` : "manual";
  return `${schedule.enabled ? "enabled" : "disabled"} · ${schedule.recurrence || "manual"} · ${next}`;
}

export function ProjectRunsBoardCard({
  item,
  selected,
  onSelect,
}: {
  item: BoardItem;
  selected: boolean;
  onSelect: () => void;
}) {
  let title = "";
  let meta = "";
  let age = "";
  let urgent = false;
  let tokens: { label: string; tone?: "red" | "green" | "blue" }[] = [];
  let icon: ReactNode = null;

  if (item.kind === "run") {
    const run = item.run;
    title = runTitle(run);
    meta = item.column === "running" ? `${runMetaLine(run)} · ${evidenceLine(run)}` : `${formatRunTime(itemTimestamp(run))} · ${evidenceLine(run)}`;
    age = isActiveRun(run) ? compactAge(itemTimestamp(run) || startedTimestamp(run)) : reviewStatus(run).replaceAll("_", " ") || runStatus(run);
    urgent = isStaleActive(run) || ["blocked", "changes_requested"].includes(reviewStatus(run));
    tokens = [
      urgent ? { label: isStaleActive(run) ? "stale" : reviewStatus(run).replaceAll("_", " "), tone: "red" } : { label: runStatus(run) || "run", tone: isClosedRun(run) ? "green" : undefined },
      run.receipt ? { label: "receipt", tone: "green" } : { label: "no receipt" },
      run.task.session_id ? { label: "session", tone: "blue" } : { label: "no session" },
    ];
    icon = item.column === "review" ? <GitMerge size={13} /> : item.column === "closed" ? <CheckCircle2 size={13} /> : <GitBranch size={13} />;
  } else if (item.kind === "schedule") {
    title = item.schedule.title;
    meta = scheduleNextLine(item.schedule);
    age = item.schedule.enabled ? "active" : "paused";
    tokens = [
      { label: item.schedule.recurrence || "manual", tone: item.schedule.enabled ? "green" : undefined },
      { label: `${item.schedule.run_count} runs` },
      item.schedule.last_run?.session_id ? { label: "last session", tone: "blue" } : { label: "no session" },
    ];
    icon = <CalendarClock size={13} />;
  } else if (item.kind === "review_session") {
    title = item.session.title || "Project coding-run review";
    meta = `${item.session.run_count} run${item.session.run_count === 1 ? "" : "s"} · latest ${formatRunTime(item.session.latest_activity_at || item.session.created_at)}`;
    age = item.session.task_status || item.session.status;
    urgent = String(item.session.status || "").toLowerCase() === "blocked";
    tokens = [
      { label: item.session.status, tone: urgent ? "red" : undefined },
      { label: "review agent", tone: "blue" },
    ];
    icon = <GitMerge size={13} />;
  } else if (item.kind === "batch") {
    title = batchTitle(item.batch);
    meta = `${item.batch.run_count} run${item.batch.run_count === 1 ? "" : "s"} · ready ${item.batch.summary?.ready_count ?? 0} · unreviewed ${item.batch.summary?.unreviewed_count ?? 0}`;
    age = item.batch.status;
    tokens = [{ label: "batch", tone: "blue" }, { label: item.batch.status }];
    icon = <GitMerge size={13} />;
  } else if (item.kind === "inbox") {
    title = item.item.title;
    meta = item.item.summary_line || item.item.next_action || item.item.state;
    age = item.item.state;
    tokens = [{ label: item.item.state }, item.item.launch_batch_id ? { label: `batch ${shortId(item.item.launch_batch_id)}` } : { label: "inbox" }];
    icon = <FileText size={13} />;
  } else {
    title = item.kind === "new_run" ? "Start a new run" : "Schedule a prompt";
    meta = item.kind === "new_run" ? "Launch work into a visible channel session." : "Create a recurring Project run prompt.";
    age = "new";
    tokens = [{ label: "launcher", tone: "blue" }];
    icon = item.kind === "new_run" ? <Play size={13} /> : <CalendarClock size={13} />;
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "w-full rounded-md border px-2 py-1.5 text-left transition-colors duration-100",
        selected ? "border-accent bg-accent/[0.08]" : urgent ? "border-danger/45 bg-danger/10" : "border-surface-border/55 bg-surface-raised/45 hover:bg-surface-overlay/40",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-1.5">
        <div className="flex min-w-0 items-start gap-1.5">
          <span className="mt-0.5 shrink-0 text-text-dim">{icon}</span>
          <span className="line-clamp-2 min-w-0 text-[12px] font-semibold leading-4 text-text">{title}</span>
        </div>
        <span className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold leading-3 ${urgent ? "bg-danger/10 text-danger-muted" : "bg-surface-overlay/70 text-text-dim"}`}>
          {age}
        </span>
      </div>
      <div className="mt-1 truncate text-[11px] leading-4 text-text-muted">{meta}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {tokens.filter(Boolean).slice(0, 3).map((token) => (
          <span
            key={token.label}
            className={[
              "rounded px-1 py-0.5 text-[10px] font-semibold leading-3",
              token.tone === "red" ? "bg-danger/10 text-danger-muted" : token.tone === "green" ? "bg-success/10 text-success" : token.tone === "blue" ? "bg-accent/10 text-accent" : "bg-surface-overlay/70 text-text-dim",
            ].join(" ")}
          >
            {token.label}
          </span>
        ))}
      </div>
    </button>
  );
}
