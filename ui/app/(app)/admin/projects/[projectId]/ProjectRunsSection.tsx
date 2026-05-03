import { Link } from "react-router-dom";
import {
  CalendarClock,
  Check,
  CheckCircle2,
  FileText,
  GitBranch,
  GitMerge,
  MessageSquarePlus,
  Play,
  RefreshCcw,
  Repeat2,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  useCancelProjectCodingRun,
  useCleanupProjectCodingRun,
  useContinueProjectCodingRun,
  useCreateProjectBlueprintFromCurrent,
  useCreateProjectCodingRun,
  useCreateProjectCodingRunReviewSession,
  useCreateProjectCodingRunSchedule,
  useDisableProjectCodingRunLoop,
  useDisableProjectCodingRunSchedule,
  useMarkProjectCodingRunReviewed,
  useProjectCodingRunReviewBatches,
  useProjectCodingRunReviewSessions,
  useProjectCodingRunSchedules,
  useProjectCodingRuns,
  useProjectFactoryReviewInbox,
  useRefreshProjectCodingRun,
  useRunProjectCodingRunScheduleNow,
  useManageSessionExecutionEnvironment,
  useSessionExecutionEnvironment,
  useUpdateProjectCodingRunSchedule,
} from "@/src/api/hooks/useProjects";
import type { MachineTargetGrant } from "@/src/api/hooks/useTasks";
import { DateTimePicker } from "@/src/components/shared/DateTimePicker";
import { FormRow, SelectInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { ActionButton, EmptyState } from "@/src/components/shared/SettingsControls";
import type {
  Channel,
  Project,
  ProjectCodingRun,
  ProjectCodingRunReviewBatch,
  ProjectCodingRunReviewSessionLedger,
  ProjectCodingRunSchedule,
  ProjectFactoryReviewInboxItem,
  ProjectRunReceipt,
} from "@/src/types/api";
import {
  ExecutionAccessControl,
  executionAccessLine,
  formatRunTime,
  RowLink,
} from "./ProjectRunControls";

type BoardColumnKey = "backlog" | "scheduled" | "running" | "review" | "closed";
type BoardItem =
  | { id: string; kind: "run"; column: BoardColumnKey; run: ProjectCodingRun }
  | { id: string; kind: "schedule"; column: "scheduled"; schedule: ProjectCodingRunSchedule }
  | { id: string; kind: "review_session"; column: "review"; session: ProjectCodingRunReviewSessionLedger }
  | { id: string; kind: "batch"; column: "backlog"; batch: ProjectCodingRunReviewBatch }
  | { id: string; kind: "inbox"; column: "backlog"; item: ProjectFactoryReviewInboxItem }
  | { id: string; kind: "new_run"; column: "backlog" }
  | { id: string; kind: "new_schedule"; column: "scheduled" };

const TERMINAL_STATUSES = new Set(["complete", "completed", "cancelled", "canceled", "failed"]);
const STALE_ACTIVE_MS = 30 * 60 * 1000;

function runTitle(run: ProjectCodingRun) {
  return run.task.title || "Project coding run";
}

function runDescription(run: ProjectCodingRun) {
  return run.request || "";
}

function shortId(value?: string | null) {
  if (!value) return "";
  const parts = value.split(":");
  return (parts[1] || value).slice(0, 8);
}

function runStatus(run: ProjectCodingRun) {
  return String(run.task?.status || run.status || "").toLowerCase();
}

function reviewStatus(run: ProjectCodingRun) {
  return String(run.review_queue_state || run.review?.status || run.status || "").toLowerCase();
}

function isActiveRun(run: ProjectCodingRun) {
  const status = runStatus(run);
  return status === "pending" || status === "running";
}

function isClosedRun(run: ProjectCodingRun) {
  const status = runStatus(run);
  const review = reviewStatus(run);
  return TERMINAL_STATUSES.has(status) || review === "reviewed" || Boolean(run.review?.reviewed);
}

function isReviewRun(run: ProjectCodingRun) {
  if (isClosedRun(run)) return false;
  const review = reviewStatus(run);
  return ["blocked", "changes_requested", "ready_for_review", "needs_review", "missing_evidence", "pending_evidence", "reviewing", "follow_up_running"].includes(review);
}

function isActiveReviewSession(session: ProjectCodingRunReviewSessionLedger) {
  const status = String(session.task_status || session.status || "").toLowerCase();
  return Boolean(session.actions?.active) || status === "pending" || status === "running" || status === "active";
}

function itemTimestamp(run: ProjectCodingRun) {
  return run.updated_at || run.task.completed_at || run.created_at || run.task.created_at || null;
}

function startedTimestamp(run: ProjectCodingRun) {
  return run.created_at || run.task.created_at || run.task.run_at || null;
}

function ageMs(value?: string | null) {
  if (!value) return 0;
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return 0;
  return Math.max(0, Date.now() - time);
}

function compactAge(value?: string | null) {
  const ms = ageMs(value);
  if (ms <= 0) return "now";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (hours < 48) return remaining ? `${hours}h ${remaining}m` : `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function isStaleActive(run: ProjectCodingRun) {
  return isActiveRun(run) && ageMs(itemTimestamp(run) || startedTimestamp(run)) > STALE_ACTIVE_MS && !run.receipt;
}

function evidenceLine(run: ProjectCodingRun) {
  const evidence = run.review?.evidence;
  if (evidence) {
    return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files`;
  }
  if (!run.receipt) return "no receipt";
  return `${run.receipt.tests?.length ?? 0} tests · ${run.receipt.screenshots?.length ?? 0} screenshots · ${run.receipt.changed_files?.length ?? 0} files`;
}

function runMetaLine(run: ProjectCodingRun) {
  const pieces = [
    startedTimestamp(run) ? `started ${formatRunTime(startedTimestamp(run))}` : null,
    run.branch ? `branch ${run.branch}` : null,
    run.repo?.path ? String(run.repo.path) : null,
  ].filter(Boolean);
  return pieces.join(" · ") || "Project coding run";
}

function sessionPathForRun(run: ProjectCodingRun) {
  return run.task.channel_id && run.task.session_id ? `/channels/${run.task.channel_id}/session/${run.task.session_id}` : null;
}

function sessionPathForScheduleRun(run?: ProjectCodingRunSchedule["last_run"] | null) {
  return run?.channel_id && run.session_id ? `/channels/${run.channel_id}/session/${run.session_id}` : null;
}

function batchTitle(batch: ProjectCodingRunReviewBatch) {
  return batch.summary?.title || `Launch batch ${shortId(batch.id)}`;
}

function scheduleNextLine(schedule: ProjectCodingRunSchedule) {
  return `${schedule.enabled ? "enabled" : "disabled"} · ${schedule.recurrence || "manual"} · next ${formatRunTime(schedule.scheduled_at)}`;
}

function classifyRun(run: ProjectCodingRun): BoardColumnKey {
  if (isClosedRun(run)) return "closed";
  if (isActiveRun(run)) return "running";
  if (isReviewRun(run)) return "review";
  return "backlog";
}

function itemPriority(item: BoardItem) {
  if (item.kind === "run") {
    if (isStaleActive(item.run)) return 0;
    const review = reviewStatus(item.run);
    if (review === "blocked" || review === "changes_requested") return 1;
    if (isActiveRun(item.run)) return 2;
    if (isReviewRun(item.run)) return 3;
    if (isClosedRun(item.run)) return 8;
    return 5;
  }
  if (item.kind === "review_session") return item.session.actions?.active ? 2 : 6;
  if (item.kind === "schedule") return item.schedule.enabled ? 4 : 7;
  if (item.kind === "batch") return 5;
  if (item.kind === "inbox") return 5;
  return 9;
}

function itemSortTime(item: BoardItem) {
  if (item.kind === "run") return itemTimestamp(item.run) || "";
  if (item.kind === "review_session") return item.session.latest_activity_at || item.session.created_at || "";
  if (item.kind === "schedule") return item.schedule.scheduled_at || item.schedule.created_at || "";
  if (item.kind === "inbox") return item.item.updated_at || item.item.created_at || "";
  return "";
}

function columnLabel(key: BoardColumnKey) {
  if (key === "backlog") return "Backlog / ready";
  if (key === "scheduled") return "Scheduled";
  if (key === "running") return "Running";
  if (key === "review") return "Human review";
  return "Closed";
}

function BoardCard({
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
  let icon: React.ReactNode = null;

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

function DetailRow({ label, value }: { label: string; value?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-t border-surface-border/45 pt-2 text-[12px]">
      <span className="text-text-dim">{label}</span>
      <span className="min-w-0 text-right font-semibold text-text-muted">{value || "none"}</span>
    </div>
  );
}

function compactPath(value?: string | null) {
  if (!value) return "none";
  const parts = value.split("/").filter(Boolean);
  return parts.length > 4 ? `.../${parts.slice(-4).join("/")}` : value;
}

function InspectorPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md bg-surface-raised/55 p-3">
      <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-text-dim">{title}</div>
      {children}
    </div>
  );
}

function DetailDrawer({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-surface/55 backdrop-blur-[1px]" role="dialog" aria-modal="true" onMouseDown={onClose}>
      <div className="h-full w-full max-w-[560px] overflow-auto border-l border-surface-border bg-surface px-4 py-4" onMouseDown={(event) => event.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0 text-sm font-semibold text-text">{title}</div>
          <button type="button" className="rounded-md p-1.5 text-text-muted hover:bg-surface-overlay hover:text-text" onClick={onClose} aria-label="Close details">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ProjectRunsSection({
  project,
  channels,
}: {
  project: Project;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
  receipts?: ProjectRunReceipt[];
}) {
  const { data: runs = [] } = useProjectCodingRuns(project.id);
  const { data: schedules = [] } = useProjectCodingRunSchedules(project.id);
  const { data: reviewBatches = [] } = useProjectCodingRunReviewBatches(project.id);
  const { data: reviewSessions = [] } = useProjectCodingRunReviewSessions(project.id);
  const { data: reviewInbox } = useProjectFactoryReviewInbox(50);

  const createRun = useCreateProjectCodingRun(project.id);
  const createBlueprint = useCreateProjectBlueprintFromCurrent(project.id);
  const continueRun = useContinueProjectCodingRun(project.id);
  const refreshRun = useRefreshProjectCodingRun(project.id);
  const markReviewed = useMarkProjectCodingRunReviewed(project.id);
  const cleanupRun = useCleanupProjectCodingRun(project.id);
  const cancelRun = useCancelProjectCodingRun(project.id);
  const disableLoop = useDisableProjectCodingRunLoop(project.id);
  const createReviewSession = useCreateProjectCodingRunReviewSession(project.id);
  const createSchedule = useCreateProjectCodingRunSchedule(project.id);
  const updateSchedule = useUpdateProjectCodingRunSchedule(project.id);
  const runScheduleNow = useRunProjectCodingRunScheduleNow(project.id);
  const disableSchedule = useDisableProjectCodingRunSchedule(project.id);

  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [selectedRepoPath, setSelectedRepoPath] = useState("");
  const [request, setRequest] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [runMachineTargetGrant, setRunMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [loopMaxIterations, setLoopMaxIterations] = useState(3);
  const [loopStopCondition, setLoopStopCondition] = useState("Stop when the requested work is implemented, verified, and ready for human review.");
  const [reviewPrompt, setReviewPrompt] = useState("Review the selected PRs. Merge only accepted work to development, then mark those runs reviewed with links and blockers.");
  const [reviewMachineTargetGrant, setReviewMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [changeFeedback, setChangeFeedback] = useState("");
  const [scheduleTitle, setScheduleTitle] = useState("Weekly Project review");
  const [scheduleRequest, setScheduleRequest] = useState("Review the Project for regressions, stale PRs, missing tests, and architecture issues. If changes are needed, implement them, run tests/screenshots, open a PR, and publish a Project run receipt. If no change is needed, publish a no-change receipt.");
  const [scheduleStart, setScheduleStart] = useState("");
  const [scheduleRecurrence, setScheduleRecurrence] = useState("+1w");
  const [scheduleMachineTargetGrant, setScheduleMachineTargetGrant] = useState<MachineTargetGrant | null>(null);

  useEffect(() => {
    if (!selectedChannelId && channels && channels.length > 0) {
      setSelectedChannelId(channels[0].id);
    }
  }, [channels, selectedChannelId]);

  const selectedChannel = channels?.find((channel) => channel.id === selectedChannelId);
  const hasBlueprintSnapshot = Boolean(project.metadata_?.blueprint_snapshot);
  const blueprintRepos = useMemo(() => {
    const raw = project.metadata_?.blueprint_snapshot?.repos;
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((repo): repo is Record<string, any> => Boolean(repo) && typeof repo === "object")
      .map((repo) => ({
        label: `${repo.name || repo.path || "Repository"}${repo.branch ? ` · ${repo.branch}` : ""}`,
        value: String(repo.path || repo.name || ""),
      }))
      .filter((repo) => repo.value);
  }, [project.metadata_]);

  useEffect(() => {
    if (!selectedRepoPath && blueprintRepos.length > 0) {
      setSelectedRepoPath(blueprintRepos[0].value);
    }
  }, [blueprintRepos, selectedRepoPath]);

  const inboxItems = useMemo(() => {
    const runTaskIds = new Set(runs.map((run) => run.task.id));
    return (reviewInbox?.items ?? [])
      .filter((item) => item.project_id === project.id)
      .filter((item) => !runTaskIds.has(item.task_id))
      .slice(0, 8);
  }, [project.id, reviewInbox?.items, runs]);

  const boardItems = useMemo<BoardItem[]>(() => {
    const items: BoardItem[] = [
      { id: "action:new-run", kind: "new_run", column: "backlog" },
      { id: "action:new-schedule", kind: "new_schedule", column: "scheduled" },
      ...schedules.map((schedule) => ({ id: `schedule:${schedule.id}`, kind: "schedule" as const, column: "scheduled" as const, schedule })),
      ...reviewSessions.filter(isActiveReviewSession).map((session) => ({ id: `review-session:${session.id}`, kind: "review_session" as const, column: "review" as const, session })),
      ...runs.map((run) => ({ id: `run:${run.id}`, kind: "run" as const, column: classifyRun(run), run })),
      ...reviewBatches.filter((batch) => batch.status !== "reviewed").map((batch) => ({ id: `batch:${batch.id}`, kind: "batch" as const, column: "backlog" as const, batch })),
      ...inboxItems.map((item) => ({ id: `inbox:${item.id}`, kind: "inbox" as const, column: "backlog" as const, item })),
    ];
    return items.sort((a, b) => {
      const priority = itemPriority(a) - itemPriority(b);
      if (priority !== 0) return priority;
      return itemSortTime(b).localeCompare(itemSortTime(a));
    });
  }, [inboxItems, reviewBatches, reviewSessions, runs, schedules]);

  const columns = useMemo(() => {
    const map: Record<BoardColumnKey, BoardItem[]> = { backlog: [], scheduled: [], running: [], review: [], closed: [] };
    for (const item of boardItems) map[item.column].push(item);
    return map;
  }, [boardItems]);

  useEffect(() => {
    if (!selectedItemId || boardItems.some((item) => item.id === selectedItemId)) return;
    setSelectedItemId("");
  }, [boardItems, selectedItemId]);

  const selectedItem = boardItems.find((item) => item.id === selectedItemId);
  const activeRuns = columns.running.filter((item) => item.kind === "run").length;
  const staleRuns = columns.running.filter((item) => item.kind === "run" && isStaleActive(item.run)).length;
  const reviewCount = columns.review.length;
  const scheduleCount = columns.scheduled.filter((item) => item.kind === "schedule").length;
  const closedCount = columns.closed.length;

  const startRun = () => {
    if (!selectedChannel || !hasBlueprintSnapshot || createRun.isPending) return;
    createRun.mutate(
      {
        channel_id: selectedChannel.id,
        request: request.trim(),
        repo_path: selectedRepoPath || null,
        machine_target_grant: runMachineTargetGrant,
        loop_policy: loopEnabled
          ? {
            enabled: true,
            max_iterations: loopMaxIterations,
            stop_condition: loopStopCondition.trim(),
          }
          : null,
      },
      {
        onSuccess: (run) => {
          setSelectedItemId(`run:${run.id}`);
          setRequest("");
        },
      },
    );
  };

  const startSchedule = () => {
    if (!selectedChannel || createSchedule.isPending) return;
    createSchedule.mutate(
      {
        channel_id: selectedChannel.id,
        title: scheduleTitle.trim() || "Scheduled Project coding run",
        request: scheduleRequest.trim(),
        scheduled_at: scheduleStart || null,
        recurrence: scheduleRecurrence || "+1w",
        machine_target_grant: scheduleMachineTargetGrant,
      },
      { onSuccess: (schedule) => setSelectedItemId(`schedule:${schedule.id}`) },
    );
  };

  const launchReviewForRun = (run: ProjectCodingRun) => {
    if (!selectedChannel || createReviewSession.isPending) return;
    createReviewSession.mutate({
      channel_id: selectedChannel.id,
      task_ids: [run.task.id],
      prompt: `${reviewPrompt.trim()}\n\nReview Project coding run ${run.task.id}. Preserve receipt, screenshot, PR, and follow-up provenance.`,
      merge_method: "squash",
      machine_target_grant: reviewMachineTargetGrant,
    });
  };

  const launchReviewForBatch = (batch: ProjectCodingRunReviewBatch) => {
    if (!selectedChannel || !batch.task_ids?.length || createReviewSession.isPending) return;
    createReviewSession.mutate({
      channel_id: selectedChannel.id,
      task_ids: batch.task_ids,
      prompt: `${reviewPrompt.trim()}\n\nReview launch batch ${batch.id}. Keep finalization provenance linked to this batch.`,
      merge_method: "squash",
      machine_target_grant: reviewMachineTargetGrant,
    });
  };

  const submitFollowUp = (run: ProjectCodingRun) => {
    if (continueRun.isPending || !changeFeedback.trim()) return;
    continueRun.mutate(
      { taskId: run.task.id, feedback: changeFeedback.trim() },
      { onSuccess: (next) => {
        setChangeFeedback("");
        setSelectedItemId(`run:${next.id}`);
      } },
    );
  };

  return (
    <div data-testid="project-workspace-runs" className="flex h-full min-h-[calc(100vh-150px)] w-full flex-col overflow-hidden px-3 py-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-surface-raised/35 px-2 py-1.5 text-xs">
        <span className={`font-semibold ${staleRuns > 0 ? "text-danger-muted" : "text-text"}`}>{staleRuns > 0 ? `${staleRuns} needs operator` : "clear"}</span>
        <span className="text-text-dim">running <span className="font-semibold text-text-muted">{activeRuns}</span></span>
        <span className="text-text-dim">review <span className="font-semibold text-text-muted">{reviewCount}</span></span>
        <span className="text-text-dim">schedules <span className="font-semibold text-text-muted">{scheduleCount}</span></span>
        <span className="text-text-dim">closed <span className="font-semibold text-text-muted">{closedCount}</span></span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="grid min-h-full min-w-[920px] grid-cols-[repeat(5,minmax(180px,1fr))] gap-1.5">
          {(["backlog", "scheduled", "running", "review", "closed"] as BoardColumnKey[]).map((column) => (
            <div key={column} className="min-h-[560px] bg-surface-raised/20 px-1.5 py-1.5">
              <div className="mb-1.5 flex items-center justify-between gap-2 px-1">
                <div className="truncate text-[10px] font-bold uppercase tracking-[0.08em] text-text-dim/80">{columnLabel(column)}</div>
                <div className="text-[10px] font-semibold text-text-dim">{columns[column].length}</div>
              </div>
              <div className="grid auto-rows-max grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-1.5">
                {columns[column].length === 0 ? (
                  <div className="h-10 rounded-md bg-surface/20" aria-hidden="true" />
                ) : (
                  columns[column].map((item) => (
                    <BoardCard
                      key={item.id}
                      item={item}
                      selected={item.id === selectedItem?.id}
                      onSelect={() => setSelectedItemId(item.id)}
                    />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {selectedItem && (
        <DetailDrawer title={selectedItem.kind === "run" ? runTitle(selectedItem.run) : selectedItem.kind === "schedule" ? selectedItem.schedule.title : selectedItem.kind === "batch" ? batchTitle(selectedItem.batch) : selectedItem.kind === "review_session" ? selectedItem.session.title || "Review agent" : selectedItem.kind === "inbox" ? selectedItem.item.title : selectedItem.kind === "new_run" ? "Start a new run" : "Schedule a prompt"} onClose={() => setSelectedItemId("")}>
          <Inspector
            project={project}
            item={selectedItem}
            channels={channels}
            selectedChannelId={selectedChannelId}
            setSelectedChannelId={setSelectedChannelId}
            blueprintRepos={blueprintRepos}
            selectedRepoPath={selectedRepoPath}
            setSelectedRepoPath={setSelectedRepoPath}
            request={request}
            setRequest={setRequest}
            runMachineTargetGrant={runMachineTargetGrant}
            setRunMachineTargetGrant={setRunMachineTargetGrant}
            loopEnabled={loopEnabled}
            setLoopEnabled={setLoopEnabled}
            loopMaxIterations={loopMaxIterations}
            setLoopMaxIterations={setLoopMaxIterations}
            loopStopCondition={loopStopCondition}
            setLoopStopCondition={setLoopStopCondition}
            hasBlueprintSnapshot={hasBlueprintSnapshot}
            createBlueprintPending={createBlueprint.isPending}
            onCreateBlueprint={() => createBlueprint.mutate({ apply_to_project: true })}
            createRunPending={createRun.isPending}
            onStartRun={startRun}
            createRunError={createRun.error}
            scheduleTitle={scheduleTitle}
            setScheduleTitle={setScheduleTitle}
            scheduleRequest={scheduleRequest}
            setScheduleRequest={setScheduleRequest}
            scheduleStart={scheduleStart}
            setScheduleStart={setScheduleStart}
            scheduleRecurrence={scheduleRecurrence}
            setScheduleRecurrence={setScheduleRecurrence}
            scheduleMachineTargetGrant={scheduleMachineTargetGrant}
            setScheduleMachineTargetGrant={setScheduleMachineTargetGrant}
            createSchedulePending={createSchedule.isPending}
            onStartSchedule={startSchedule}
            runBusy={refreshRun.isPending || markReviewed.isPending || cleanupRun.isPending || cancelRun.isPending || disableLoop.isPending || continueRun.isPending}
            onRefreshRun={(run) => refreshRun.mutate(run.task.id)}
            onCancelRun={(run) => cancelRun.mutate(run.task.id)}
            onCleanupRun={(run) => cleanupRun.mutate(run.task.id)}
            onMarkReviewed={(run) => markReviewed.mutate(run.task.id)}
            onDisableLoop={(run) => disableLoop.mutate(run.task.id)}
            onLaunchReviewForRun={launchReviewForRun}
            reviewPrompt={reviewPrompt}
            setReviewPrompt={setReviewPrompt}
            reviewMachineTargetGrant={reviewMachineTargetGrant}
            setReviewMachineTargetGrant={setReviewMachineTargetGrant}
            reviewBusy={createReviewSession.isPending}
            changeFeedback={changeFeedback}
            setChangeFeedback={setChangeFeedback}
            onSubmitFollowUp={submitFollowUp}
            onLaunchReviewForBatch={launchReviewForBatch}
            scheduleBusy={createSchedule.isPending || updateSchedule.isPending || runScheduleNow.isPending || disableSchedule.isPending}
            onRunScheduleNow={(schedule) => runScheduleNow.mutate(schedule.id, {
              onSuccess: (run) => setSelectedItemId(`run:${run.id}`),
            })}
            onDisableSchedule={(schedule) => disableSchedule.mutate(schedule.id)}
            onResumeSchedule={(schedule) => updateSchedule.mutate({ scheduleId: schedule.id, enabled: true })}
          />
        </DetailDrawer>
      )}
    </div>
  );
}

function Inspector({
  project,
  item,
  channels,
  selectedChannelId,
  setSelectedChannelId,
  blueprintRepos,
  selectedRepoPath,
  setSelectedRepoPath,
  request,
  setRequest,
  runMachineTargetGrant,
  setRunMachineTargetGrant,
  loopEnabled,
  setLoopEnabled,
  loopMaxIterations,
  setLoopMaxIterations,
  loopStopCondition,
  setLoopStopCondition,
  hasBlueprintSnapshot,
  createBlueprintPending,
  onCreateBlueprint,
  createRunPending,
  onStartRun,
  createRunError,
  scheduleTitle,
  setScheduleTitle,
  scheduleRequest,
  setScheduleRequest,
  scheduleStart,
  setScheduleStart,
  scheduleRecurrence,
  setScheduleRecurrence,
  scheduleMachineTargetGrant,
  setScheduleMachineTargetGrant,
  createSchedulePending,
  onStartSchedule,
  runBusy,
  onRefreshRun,
  onCancelRun,
  onCleanupRun,
  onMarkReviewed,
  onDisableLoop,
  onLaunchReviewForRun,
  reviewPrompt,
  setReviewPrompt,
  reviewMachineTargetGrant,
  setReviewMachineTargetGrant,
  reviewBusy,
  changeFeedback,
  setChangeFeedback,
  onSubmitFollowUp,
  onLaunchReviewForBatch,
  scheduleBusy,
  onRunScheduleNow,
  onDisableSchedule,
  onResumeSchedule,
}: {
  project: Project;
  item?: BoardItem;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
  selectedChannelId: string;
  setSelectedChannelId: (value: string) => void;
  blueprintRepos: { label: string; value: string }[];
  selectedRepoPath: string;
  setSelectedRepoPath: (value: string) => void;
  request: string;
  setRequest: (value: string) => void;
  runMachineTargetGrant: MachineTargetGrant | null;
  setRunMachineTargetGrant: (value: MachineTargetGrant | null) => void;
  loopEnabled: boolean;
  setLoopEnabled: (value: boolean) => void;
  loopMaxIterations: number;
  setLoopMaxIterations: (value: number) => void;
  loopStopCondition: string;
  setLoopStopCondition: (value: string) => void;
  hasBlueprintSnapshot: boolean;
  createBlueprintPending: boolean;
  onCreateBlueprint: () => void;
  createRunPending: boolean;
  onStartRun: () => void;
  createRunError: unknown;
  scheduleTitle: string;
  setScheduleTitle: (value: string) => void;
  scheduleRequest: string;
  setScheduleRequest: (value: string) => void;
  scheduleStart: string;
  setScheduleStart: (value: string) => void;
  scheduleRecurrence: string;
  setScheduleRecurrence: (value: string) => void;
  scheduleMachineTargetGrant: MachineTargetGrant | null;
  setScheduleMachineTargetGrant: (value: MachineTargetGrant | null) => void;
  createSchedulePending: boolean;
  onStartSchedule: () => void;
  runBusy: boolean;
  onRefreshRun: (run: ProjectCodingRun) => void;
  onCancelRun: (run: ProjectCodingRun) => void;
  onCleanupRun: (run: ProjectCodingRun) => void;
  onMarkReviewed: (run: ProjectCodingRun) => void;
  onDisableLoop: (run: ProjectCodingRun) => void;
  onLaunchReviewForRun: (run: ProjectCodingRun) => void;
  reviewPrompt: string;
  setReviewPrompt: (value: string) => void;
  reviewMachineTargetGrant: MachineTargetGrant | null;
  setReviewMachineTargetGrant: (value: MachineTargetGrant | null) => void;
  reviewBusy: boolean;
  changeFeedback: string;
  setChangeFeedback: (value: string) => void;
  onSubmitFollowUp: (run: ProjectCodingRun) => void;
  onLaunchReviewForBatch: (batch: ProjectCodingRunReviewBatch) => void;
  scheduleBusy: boolean;
  onRunScheduleNow: (schedule: ProjectCodingRunSchedule) => void;
  onDisableSchedule: (schedule: ProjectCodingRunSchedule) => void;
  onResumeSchedule: (schedule: ProjectCodingRunSchedule) => void;
}) {
  const selectedRunSessionId = item?.kind === "run" ? item.run.task.session_id : null;
  const sessionEnv = useSessionExecutionEnvironment(selectedRunSessionId);
  const manageSessionEnv = useManageSessionExecutionEnvironment(selectedRunSessionId);

  if (!item) return <EmptyState message="No Project run items are available." />;

  if (item.kind === "new_run") {
    return (
      <div className="flex flex-col gap-3">
        <InspectorPanel title="Start run">
          <div className="text-base font-semibold text-text">Start a new agent coding run</div>
          <p className="mt-1 text-[13px] text-text-muted">The run will create a visible channel session immediately.</p>
        </InspectorPanel>
        <InspectorPanel title="Request">
          <div className="flex flex-col gap-3">
            <FormRow label="Channel">
              <SelectInput
                value={selectedChannelId}
                onChange={setSelectedChannelId}
                options={
                  channels && channels.length > 0
                    ? channels.map((channel) => ({ label: `${channel.name} · ${channel.bot_id}`, value: channel.id }))
                    : [{ label: "Attach a Project channel first", value: "" }]
                }
              />
            </FormRow>
            {blueprintRepos.length > 1 && (
              <FormRow label="Repository">
                <SelectInput value={selectedRepoPath} onChange={setSelectedRepoPath} options={blueprintRepos} />
              </FormRow>
            )}
            <PromptEditor
              value={request}
              onChange={setRequest}
              label="Run request"
              placeholder="Implement the next issue, run tests, capture screenshots, and publish a handoff receipt..."
              rows={5}
              fieldType="task_prompt"
              generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
            />
            <ExecutionAccessControl value={runMachineTargetGrant} onChange={setRunMachineTargetGrant} testId="project-run-execution-access" />
            <label className="flex items-center gap-2 text-[12px] font-semibold text-text">
              <input type="checkbox" className="h-4 w-4 rounded border-input-border bg-input" checked={loopEnabled} onChange={(event) => setLoopEnabled(event.target.checked)} />
              Bounded loop
            </label>
            {loopEnabled && (
              <div className="grid gap-2">
                <FormRow label="Max iterations">
                  <SelectInput value={String(loopMaxIterations)} onChange={(value) => setLoopMaxIterations(Number(value))} options={[2, 3, 4, 5, 6, 7, 8].map((value) => ({ label: String(value), value: String(value) }))} />
                </FormRow>
                <FormRow label="Stop condition">
                  <textarea value={loopStopCondition} onChange={(event) => setLoopStopCondition(event.target.value)} rows={3} className="min-h-[72px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] text-text outline-none focus:border-accent" />
                </FormRow>
              </div>
            )}
            {!hasBlueprintSnapshot && (
              <ActionButton label={createBlueprintPending ? "Creating Blueprint" : "Create Blueprint"} icon={<FileText size={13} />} disabled={createBlueprintPending} onPress={onCreateBlueprint} />
            )}
            <ActionButton label={createRunPending ? "Starting" : "Start run"} icon={<Play size={13} />} disabled={!selectedChannelId || !hasBlueprintSnapshot || createRunPending} onPress={onStartRun} />
            {Boolean(createRunError) && <div className="text-[12px] text-danger-muted">{createRunError instanceof Error ? createRunError.message : String(createRunError || "The run could not be started.")}</div>}
          </div>
        </InspectorPanel>
      </div>
    );
  }

  if (item.kind === "new_schedule") {
    return (
      <div className="flex flex-col gap-3">
        <InspectorPanel title="Schedule prompt">
          <div className="text-base font-semibold text-text">Create a recurring Project run</div>
          <p className="mt-1 text-[13px] text-text-muted">Scheduled runs launch visible channel sessions just like manual runs.</p>
        </InspectorPanel>
        <InspectorPanel title="Schedule">
          <div className="flex flex-col gap-3">
            <FormRow label="Channel">
              <SelectInput
                value={selectedChannelId}
                onChange={setSelectedChannelId}
                options={
                  channels && channels.length > 0
                    ? channels.map((channel) => ({ label: `${channel.name} · ${channel.bot_id}`, value: channel.id }))
                    : [{ label: "Attach a Project channel first", value: "" }]
                }
              />
            </FormRow>
            <FormRow label="Title">
              <input value={scheduleTitle} onChange={(event) => setScheduleTitle(event.target.value)} className="w-full rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none focus:border-accent" />
            </FormRow>
            <FormRow label="Start">
              <DateTimePicker value={scheduleStart} onChange={setScheduleStart} />
            </FormRow>
            <FormRow label="Repeat">
              <SelectInput value={scheduleRecurrence} onChange={setScheduleRecurrence} options={[{ label: "Daily", value: "+1d" }, { label: "Weekly", value: "+1w" }, { label: "Manual", value: "" }]} />
            </FormRow>
            <PromptEditor value={scheduleRequest} onChange={setScheduleRequest} label="Scheduled run prompt" rows={5} fieldType="task_prompt" generateContext={`Project: ${project.name}. Root: /${project.root_path}`} />
            <ExecutionAccessControl value={scheduleMachineTargetGrant} onChange={setScheduleMachineTargetGrant} testId="project-schedule-execution-access" />
            <ActionButton label={createSchedulePending ? "Saving" : "Create schedule"} icon={<CalendarClock size={13} />} disabled={!selectedChannelId || createSchedulePending} onPress={onStartSchedule} />
          </div>
        </InspectorPanel>
      </div>
    );
  }

  if (item.kind === "run") {
    const run = item.run;
    const sessionPath = sessionPathForRun(run);
	    const handoffUrl = run.review?.handoff_url || run.receipt?.handoff_url || null;
	    const active = isActiveRun(run);
	    const stale = isStaleActive(run);
	    const env = sessionEnv.data;
	    const envBusy = manageSessionEnv.isPending || sessionEnv.isFetching;
	    return (
      <div className="flex flex-col gap-3">
        {stale && <div className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-3 text-[13px] font-semibold text-danger-muted">Stale running run needs a decision</div>}
        <InspectorPanel title="Selected run">
          <div className="text-base font-semibold leading-6 text-text">{runTitle(run)}</div>
          <p className="mt-1 text-[13px] text-text-muted">{runDescription(run) || run.lifecycle?.next_action || run.review_next_action || evidenceLine(run)}</p>
          <div className="mt-3 grid gap-2">
            <DetailRow label="Started" value={formatRunTime(startedTimestamp(run))} />
            <DetailRow label="Last activity" value={formatRunTime(itemTimestamp(run))} />
            <DetailRow label="Age" value={compactAge(itemTimestamp(run) || startedTimestamp(run))} />
            <DetailRow label="Status" value={runStatus(run)} />
            <DetailRow label="Review" value={reviewStatus(run).replaceAll("_", " ")} />
            <DetailRow label="Session" value={run.task.session_id ? String(run.task.session_id).slice(0, 8) : "missing"} />
            <DetailRow label="Branch" value={run.branch || "none"} />
            <DetailRow label="Evidence" value={evidenceLine(run)} />
            <DetailRow label="Dev target" value={run.dev_targets?.length ? run.dev_targets.map((target) => typeof target === "string" ? target : target.url || target.label || target.key).filter(Boolean).slice(0, 2).join(" · ") : "none"} />
	          </div>
	        </InspectorPanel>
	        <InspectorPanel title="Session environment">
	          <div className="grid gap-2">
	            <DetailRow label="Mode" value={env ? `${env.mode}${env.status ? ` · ${env.status}` : ""}` : selectedRunSessionId ? "loading" : "missing session"} />
	            <DetailRow label="Worktree" value={compactPath(env?.worktree?.worktree_path || env?.cwd)} />
	            <DetailRow label="Branch" value={env?.worktree?.branch || "none"} />
	            <DetailRow label="Docker" value={env?.docker_status ? `${env.docker_status}${env.docker_endpoint ? ` · ${env.docker_endpoint}` : ""}` : "none"} />
	            <DetailRow label="TTL" value={env?.pinned ? "pinned" : env?.expires_at ? formatRunTime(env.expires_at) : "default"} />
	          </div>
	          {selectedRunSessionId && (
	            <div className="mt-3 grid grid-cols-2 gap-2">
	              <ActionButton label="Doctor" icon={<RefreshCcw size={13} />} size="small" variant="secondary" disabled={envBusy} onPress={() => manageSessionEnv.mutate({ action: "doctor" })} />
	              {env?.status === "stopped" ? (
	                <ActionButton label="Start Docker" icon={<Play size={13} />} size="small" variant="secondary" disabled={envBusy} onPress={() => manageSessionEnv.mutate({ action: "start" })} />
	              ) : (
	                <ActionButton label="Stop Docker" icon={<Trash2 size={13} />} size="small" variant="secondary" disabled={envBusy || env?.mode !== "isolated"} onPress={() => manageSessionEnv.mutate({ action: "stop" })} />
	              )}
	              <ActionButton label="Restart Docker" icon={<RefreshCcw size={13} />} size="small" variant="secondary" disabled={envBusy || env?.mode !== "isolated"} onPress={() => manageSessionEnv.mutate({ action: "restart" })} />
	              {env?.pinned ? (
	                <ActionButton label="Unpin" size="small" variant="secondary" disabled={envBusy} onPress={() => manageSessionEnv.mutate({ action: "unpin" })} />
	              ) : (
	                <ActionButton label="Pin" size="small" variant="secondary" disabled={envBusy || !env} onPress={() => manageSessionEnv.mutate({ action: "pin" })} />
	              )}
	              <ActionButton label="Clean env" icon={<Trash2 size={13} />} size="small" variant="danger" disabled={envBusy || !env || env.mode === "shared"} onPress={() => manageSessionEnv.mutate({ action: "cleanup" })} />
	            </div>
	          )}
	        </InspectorPanel>
	        <InspectorPanel title="Actions">
          <div className="grid grid-cols-2 gap-2">
            {sessionPath && <Link className="col-span-2 inline-flex min-h-[38px] items-center justify-center rounded-md bg-accent/10 text-[13px] font-semibold text-accent hover:bg-accent/15" to={sessionPath}>Open session</Link>}
            {active && <RowLink to={`/admin/projects/${project.id}/runs/${run.task.id}/live`}>Live view</RowLink>}
            <RowLink to={`/admin/projects/${project.id}/runs/${run.task.id}`}>Review detail</RowLink>
            {handoffUrl && <RowLink href={handoffUrl}>PR / handoff</RowLink>}
            <ActionButton label="Refresh" icon={<RefreshCcw size={13} />} size="small" variant="secondary" disabled={runBusy} onPress={() => onRefreshRun(run)} />
            {active && <ActionButton label="Stop run" icon={<Trash2 size={13} />} size="small" variant="danger" disabled={runBusy} onPress={() => onCancelRun(run)} />}
            {run.review?.actions?.can_mark_reviewed && <ActionButton label="Close reviewed" icon={<Check size={13} />} size="small" variant="secondary" disabled={runBusy} onPress={() => onMarkReviewed(run)} />}
            {run.review?.actions?.can_cleanup_instance && <ActionButton label="Clean up" icon={<Trash2 size={13} />} size="small" variant="danger" disabled={runBusy} onPress={() => onCleanupRun(run)} />}
            {run.loop?.enabled && <ActionButton label="Stop loop" icon={<Repeat2 size={13} />} size="small" variant="secondary" disabled={runBusy} onPress={() => onDisableLoop(run)} />}
            {item.column === "review" && <ActionButton label={reviewBusy ? "Starting" : "Ask agent"} icon={<GitMerge size={13} />} size="small" disabled={reviewBusy} onPress={() => onLaunchReviewForRun(run)} />}
          </div>
        </InspectorPanel>
        {item.column === "review" && (
          <InspectorPanel title="Review agent prompt">
            <div className="flex flex-col gap-3">
              <PromptEditor value={reviewPrompt} onChange={setReviewPrompt} label="Review prompt" rows={3} fieldType="task_prompt" generateContext={`Project: ${project.name}. Run: ${run.task.id}`} />
              <ExecutionAccessControl value={reviewMachineTargetGrant} onChange={setReviewMachineTargetGrant} testId="project-review-execution-access" />
            </div>
          </InspectorPanel>
        )}
        {run.review?.actions?.can_request_changes && (
          <InspectorPanel title="Follow-up">
            <div className="flex flex-col gap-2">
              <textarea value={changeFeedback} onChange={(event) => setChangeFeedback(event.target.value)} rows={3} className="min-h-[84px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] text-text outline-none focus:border-accent" placeholder="Describe what the follow-up agent should fix..." />
              <ActionButton label="Start follow-up" icon={<MessageSquarePlus size={13} />} size="small" disabled={runBusy || !changeFeedback.trim()} onPress={() => onSubmitFollowUp(run)} />
            </div>
          </InspectorPanel>
        )}
      </div>
    );
  }

  if (item.kind === "schedule") {
    const schedule = item.schedule;
    const lastSessionPath = sessionPathForScheduleRun(schedule.last_run);
    return (
      <div className="flex flex-col gap-3">
        <InspectorPanel title="Scheduled run">
          <div className="text-base font-semibold text-text">{schedule.title}</div>
          <p className="mt-1 text-[13px] text-text-muted">{scheduleNextLine(schedule)}</p>
          <div className="mt-3 grid gap-2">
            <DetailRow label="Status" value={schedule.enabled ? "active" : "paused"} />
            <DetailRow label="Runs" value={schedule.run_count} />
            <DetailRow label="Last run" value={schedule.last_run ? `${schedule.last_run.status || "unknown"} · ${formatRunTime(schedule.last_run.created_at)}` : "none"} />
            <DetailRow label="Execution" value={executionAccessLine(schedule.machine_target_grant) || "default"} />
          </div>
        </InspectorPanel>
        <InspectorPanel title="Actions">
          <div className="grid grid-cols-2 gap-2">
            <ActionButton label={scheduleBusy ? "Starting" : "Run now"} icon={<Play size={13} />} size="small" disabled={scheduleBusy || !schedule.enabled} onPress={() => onRunScheduleNow(schedule)} />
            {schedule.enabled ? (
              <ActionButton label="Disable" size="small" variant="secondary" disabled={scheduleBusy} onPress={() => onDisableSchedule(schedule)} />
            ) : (
              <ActionButton label="Resume" size="small" variant="secondary" disabled={scheduleBusy} onPress={() => onResumeSchedule(schedule)} />
            )}
            {lastSessionPath && <RowLink to={lastSessionPath}>Last session</RowLink>}
          </div>
        </InspectorPanel>
        <InspectorPanel title="Prompt">
          <p className="whitespace-pre-wrap text-[13px] text-text-muted">{schedule.request || "No prompt recorded."}</p>
        </InspectorPanel>
      </div>
    );
  }

  if (item.kind === "review_session") {
    const sessionPath = item.session.channel_id && item.session.session_id ? `/channels/${item.session.channel_id}/session/${item.session.session_id}` : null;
    return (
      <div className="flex flex-col gap-3">
        <InspectorPanel title="Review agent">
          <div className="text-base font-semibold text-text">{item.session.title || "Project coding-run review"}</div>
          <p className="mt-1 text-[13px] text-text-muted">{item.session.latest_summary || `${item.session.run_count} selected run${item.session.run_count === 1 ? "" : "s"}`}</p>
          <div className="mt-3 grid gap-2">
            <DetailRow label="Status" value={item.session.task_status || item.session.status} />
            <DetailRow label="Latest activity" value={formatRunTime(item.session.latest_activity_at || item.session.created_at)} />
            <DetailRow label="Session" value={item.session.session_id ? item.session.session_id.slice(0, 8) : "missing"} />
          </div>
        </InspectorPanel>
        <InspectorPanel title="Actions">
          <div className="grid grid-cols-2 gap-2">
            {sessionPath && <RowLink to={sessionPath}>Open session</RowLink>}
            <RowLink to={`/admin/tasks/${item.session.task_id}`}>Task log</RowLink>
          </div>
        </InspectorPanel>
      </div>
    );
  }

  if (item.kind === "batch") {
    return (
      <div className="flex flex-col gap-3">
        <InspectorPanel title="Launch batch">
          <div className="text-base font-semibold text-text">{batchTitle(item.batch)}</div>
          <p className="mt-1 text-[13px] text-text-muted">{item.batch.run_count} run{item.batch.run_count === 1 ? "" : "s"} · {item.batch.status}</p>
        </InspectorPanel>
        <InspectorPanel title="Actions">
          <ActionButton label={reviewBusy ? "Starting" : "Ask agent to review batch"} icon={<GitMerge size={13} />} disabled={reviewBusy || !item.batch.actions?.can_start_review} onPress={() => onLaunchReviewForBatch(item.batch)} />
        </InspectorPanel>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <InspectorPanel title="Inbox item">
        <div className="text-base font-semibold text-text">{item.item.title}</div>
        <p className="mt-1 text-[13px] text-text-muted">{item.item.summary_line || item.item.next_action || item.item.state}</p>
      </InspectorPanel>
      <InspectorPanel title="Actions">
        <div className="grid grid-cols-2 gap-2">
          {item.item.links?.run_url && <RowLink href={item.item.links.run_url}>Open run</RowLink>}
          {item.item.links?.handoff_url && <RowLink href={item.item.links.handoff_url}>PR / handoff</RowLink>}
        </div>
      </InspectorPanel>
    </div>
  );
}
