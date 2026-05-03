import { Link } from "react-router-dom";
import { AlertTriangle, Check, CheckCircle2, FileText, GitBranch, GitMerge, MessageSquarePlus, Play, RefreshCcw, Repeat2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  useCleanupProjectCodingRun,
  useCreateProjectBlueprintFromCurrent,
  useContinueProjectCodingRun,
  useCreateProjectCodingRun,
  useDisableProjectCodingRunLoop,
  useProjectCodingRunReviewBatches,
  useProjectCodingRunReviewSessions,
  useCreateProjectCodingRunReviewSession,
  useMarkProjectCodingRunsReviewed,
  useMarkProjectCodingRunReviewed,
  useProjectCodingRuns,
  useRefreshProjectCodingRun,
} from "@/src/api/hooks/useProjects";
import type { MachineTargetGrant } from "@/src/api/hooks/useTasks";
import { FormRow, Section, SelectInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { ActionButton, EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { collapseProjectRunReceiptsForReview } from "@/src/lib/projectRunReceipts";
import type { Channel, Project, ProjectCodingRun, ProjectCodingRunReviewBatch, ProjectCodingRunReviewSessionLedger, ProjectRunReceipt } from "@/src/types/api";
import { ExecutionAccessControl, executionAccessLine, formatRunTime, RowLink, statusTone } from "./ProjectRunControls";
import { ReviewSessionsSection } from "./ReviewSessionsSection";
import { ProjectScheduledReviewsSection } from "./ProjectScheduledReviewsSection";

function compactEvidence(values?: Array<Record<string, any> | string>) {
  const items = values ?? [];
  if (items.length === 0) return "None reported";
  return items
    .slice(0, 3)
    .map((item) => (typeof item === "string" ? item : String(item.name || item.path || item.command || item.status || "record")))
    .join(", ");
}

function activitySummary(run: ProjectCodingRun) {
  const activity = run.activity ?? [];
  if (activity.length === 0) return "No recent activity recorded";
  return activity
    .slice(0, 3)
    .map((item) => String(item.summary || item.title || item.name || item.tool_name || item.kind || item.type || "activity"))
    .join(", ");
}

function isActiveCodingRun(run: ProjectCodingRun) {
  const status = String(run.task.status || run.status || "").toLowerCase();
  return status === "pending" || status === "running";
}

function isActiveReviewSession(session: ProjectCodingRunReviewSessionLedger) {
  const status = String(session.task_status || session.status || "").toLowerCase();
  return Boolean(session.actions?.active) || status === "pending" || status === "running" || status === "active";
}

function runTitle(run: ProjectCodingRun) {
  return run.request || run.task.title || "Project coding run";
}

function activeRunLine(run: ProjectCodingRun) {
  const pieces = [
    run.branch ? `Branch ${run.branch}` : null,
    workSurfaceLine(run),
    dependencyStackLine(run),
    devTargetsLine(run.dev_targets) ? `Dev targets: ${devTargetsLine(run.dev_targets)}` : null,
  ].filter(Boolean);
  return pieces.length > 0 ? pieces.join(" · ") : activitySummary(run);
}

function progressLabel(actionType?: string) {
  if (actionType === "handoff.prepare_branch") return "Branch";
  if (actionType === "handoff.push") return "Push";
  if (actionType === "handoff.open_pr") return "PR";
  if (actionType === "handoff.status") return "Status";
  return "Progress";
}

function statusMark(status?: string, summary?: string) {
  if (status === "succeeded" || status === "completed") return "ready";
  if (status === "blocked" || status === "failed") return status;
  if (status === "needs_review") return "review";
  if (status === "unknown" && String(summary || "").toLowerCase().includes("ready")) return "ready";
  return status || "reported";
}

function handoffProgressSummary(run: ProjectCodingRun) {
  const steps = run.review?.steps;
  if (steps) {
    const items = [
      ["PR", steps.pr?.status],
      ["Branch", steps.branch?.status],
      ["Status", steps.status?.status],
    ]
      .filter(([, status]) => status && status !== "missing")
      .slice(0, 3)
      .map(([label, status]) => `${label}: ${statusMark(String(status || ""))}`);
    if (items.length > 0) return items.join(" · ");
  }
  const items = (run.activity ?? [])
    .filter((item) => item.kind === "execution_receipt" && item.source?.scope === "project_coding_run")
    .slice(0, 3);
  if (items.length === 0) return null;
  return items
    .map((item) => `${progressLabel(String(item.source?.action_type || ""))}: ${statusMark(String(item.status || ""), String(item.summary || ""))}`)
    .join(" · ");
}

function evidenceSummary(run: ProjectCodingRun) {
  const lifecycleEvidence = run.lifecycle?.evidence;
  if (lifecycleEvidence) {
    return `${lifecycleEvidence.tests ?? 0} tests · ${lifecycleEvidence.screenshots ?? 0} screenshots · ${lifecycleEvidence.files ?? 0} files · ${lifecycleEvidence.dev_targets ?? 0} dev targets`;
  }
  const evidence = run.review?.evidence;
  if (evidence) {
    return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files · ${evidence.dev_targets_count ?? 0} dev targets`;
  }
  if (!run.receipt) return "No evidence receipt yet";
  return `${run.receipt.tests?.length ?? 0} tests · ${run.receipt.screenshots?.length ?? 0} screenshots · ${run.receipt.changed_files?.length ?? 0} files · ${run.receipt.dev_targets?.length ?? 0} dev targets`;
}

function reviewStatusLabel(run: ProjectCodingRun) {
  return run.review?.status || run.status;
}

function reviewQueueState(run: ProjectCodingRun) {
  return run.review_queue_state || reviewStatusLabel(run);
}

function reviewQueueLabel(state?: string | null) {
  return String(state || "needs_review").replaceAll("_", " ");
}

/**
 * Symphony run_phase chip — fine-grained "what is this run doing right now".
 * Reads `lifecycle.run_phase` (4BG.3 / 4BB.5 surface). Renders nothing in the
 * steady-state "reviewed" case; otherwise a compact monochrome chip plus a
 * separate warning badge when the run is stalled.
 */
function RunPhaseChip({ run }: { run: ProjectCodingRun }) {
  // `lifecycle` is `Record[str, Any]` server-side, not formally modeled in the
  // OpenAPI schema. Read `run_phase` (4BG.3) via a narrow accessor.
  const phase = (run.lifecycle as Record<string, unknown> | undefined)?.run_phase as string | undefined;
  if (!phase || phase === "reviewed") return null;
  const stalled = phase === "stalled";
  const className = stalled
    ? "inline-flex items-center gap-1 rounded bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning"
    : "inline-flex items-center gap-1 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] font-medium text-text-muted";
  return (
    <span className={className} title={stalled ? "Run has not produced progress recently — load project/runs/recovery." : `Run phase: ${phase}`}>
      {String(phase).replaceAll("_", " ")}
    </span>
  );
}

function isHumanReviewQueueRun(run: ProjectCodingRun) {
  const state = String(reviewQueueState(run) || "").toLowerCase();
  if (state === "reviewed") return false;
  if (isActiveCodingRun(run) && !["reviewing", "follow_up_running", "changes_requested", "blocked"].includes(state)) {
    return false;
  }
  return true;
}

function reviewQueueDescription(run: ProjectCodingRun) {
  return run.lifecycle?.next_action || run.review_next_action || reviewLine(run) || evidenceSummary(run);
}

function reviewAgentTaskId(run: ProjectCodingRun) {
  return run.review?.review_task_id || null;
}

function isAgentReviewRunning(run: ProjectCodingRun) {
  const state = String(reviewQueueState(run) || "").toLowerCase();
  return state === "reviewing" || state === "follow_up_running";
}

function reviewAgentLine(run: ProjectCodingRun) {
  const taskId = reviewAgentTaskId(run);
  if (isAgentReviewRunning(run)) {
    return `Agent review running${taskId ? ` · task ${String(taskId).slice(0, 8)}` : ""}`;
  }
  if (taskId) return `Latest agent review task ${String(taskId).slice(0, 8)}`;
  return null;
}

function reviewLine(run: ProjectCodingRun) {
  if (run.lifecycle?.headline) return run.lifecycle.headline;
  const review = run.review;
  if (!review) return null;
  const pieces = [
    review.pr?.state ? `PR ${String(review.pr.state).toLowerCase()}` : review.handoff_url ? "PR linked" : null,
    review.pr?.checks_status ? `checks ${review.pr.checks_status}` : null,
    review.merge_method ? `merge ${review.merge_method}` : null,
    review.merged_at ? `merged ${formatRunTime(review.merged_at)}` : null,
    review.merge_commit_sha ? `commit ${String(review.merge_commit_sha).slice(0, 7)}` : null,
    review.review_task_id ? `review task ${String(review.review_task_id).slice(0, 8)}` : null,
    review.instance?.status ? `workspace ${review.instance.status}` : null,
  ].filter(Boolean);
  if (review.blocker) return `Blocker: ${review.blocker}`;
  return pieces.length > 0 ? pieces.join(" · ") : null;
}

function lineageLine(run: ProjectCodingRun) {
  const parts = [];
  if ((run.continuation_index ?? 0) > 0) parts.push(`Follow-up ${run.continuation_index}`);
  if ((run.continuation_count ?? 0) > 0) parts.push(`${run.continuation_count} follow-up${run.continuation_count === 1 ? "" : "s"}`);
  if (run.latest_continuation?.review_status || run.latest_continuation?.status) {
    parts.push(`latest ${run.latest_continuation.review_status || run.latest_continuation.status}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function loopLine(run: ProjectCodingRun) {
  const loop = run.loop;
  if (!loop?.enabled) return null;
  const pieces = [
    `Loop ${loop.state || "waiting"}`,
    `iteration ${loop.iteration || 1}/${loop.max_iterations || 1}`,
    loop.latest_decision ? `decision ${loop.latest_decision}` : null,
    loop.stop_reason ? `stop ${loop.stop_reason.replaceAll("_", " ")}` : null,
  ].filter(Boolean);
  return pieces.join(" · ");
}

function dependencyStackLine(run: ProjectCodingRun) {
  const stack = run.dependency_stack;
  if (!stack?.configured) return null;
  const instance = stack.instance;
  if (!instance) return "Dependency stack: not prepared";
  const target = instance.source_path || instance.id;
  const envKeys = Object.keys(instance.env ?? {});
  return `Dependency stack: ${instance.status}${target ? ` · ${target}` : ""}${envKeys.length ? ` · env ${envKeys.length}` : ""}`;
}

function workSurfaceLine(run: ProjectCodingRun) {
  const surface = run.work_surface;
  if (!surface) return null;
  if (surface.blocker) return `Work surface: ${surface.blocker}`;
  if (surface.kind === "project_instance") {
    const label = surface.project_instance_id ? surface.project_instance_id.slice(0, 8) : "pending";
    const path = surface.display_path || (surface.root_path ? `/${surface.root_path}` : null);
    return `Work surface: isolated ${label}${surface.status ? ` · ${surface.status}` : ""}${path ? ` · ${path}` : ""}`;
  }
  if (surface.kind === "project") {
    return `Work surface: shared Project root${surface.display_path ? ` · ${surface.display_path}` : ""}`;
  }
  return surface.kind ? `Work surface: ${surface.kind}` : null;
}

function shortBatchId(value?: string | null) {
  if (!value) return "";
  const parts = value.split(":");
  return (parts[1] || value).slice(0, 8);
}

function devTargetsLine(targets?: Array<Record<string, any> | string>) {
  const rows = (targets ?? []).filter(Boolean);
  if (rows.length === 0) return null;
  return rows
    .slice(0, 2)
    .map((target) => {
      if (typeof target === "string") return target;
      const label = target.label || target.key || "dev";
      const url = target.url || target[target.url_env] || "";
      const port = target.port || target[target.port_env] || "";
      return `${label}${url ? ` ${url}` : port ? ` :${port}` : ""}`;
    })
    .join(" · ");
}

function batchEvidenceLine(batch: ProjectCodingRunReviewBatch) {
  const evidence = batch.evidence ?? {};
  return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files`;
}

function batchStatusLine(batch: ProjectCodingRunReviewBatch) {
  const counts = batch.status_counts ?? {};
  const ordered = ["reviewed", "ready_for_review", "reviewing", "running", "pending", "blocked", "changes_requested", "failed"];
  const pieces = ordered
    .filter((key) => counts[key])
    .map((key) => `${counts[key]} ${key.replaceAll("_", " ")}`);
  return pieces.length ? pieces.join(" · ") : `${batch.run_count} run${batch.run_count === 1 ? "" : "s"}`;
}

function batchSourceLine(batch: ProjectCodingRunReviewBatch) {
  const packs = batch.source_work_packs ?? [];
  if (packs.length === 0) return "No source work packs linked";
  return packs.slice(0, 2).map((pack) => pack.title).join(" · ") + (packs.length > 2 ? ` · +${packs.length - 2}` : "");
}

function RunActionLinks({ run }: { run: ProjectCodingRun }) {
  const status = String(run.task?.status || run.status || "").toLowerCase();
  const inFlight = status === "running" || status === "pending" || (run.loop?.enabled && run.loop?.state && run.loop.state !== "stopped");
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {inFlight && <RowLink to={`/admin/projects/${run.project_id}/runs/${run.task.id}/live`}>Live view</RowLink>}
      <RowLink to={`/admin/projects/${run.project_id}/runs/${run.task.id}`}>Open review page</RowLink>
      {(run.review?.handoff_url || run.receipt?.handoff_url) && <RowLink href={run.review?.handoff_url || run.receipt?.handoff_url || undefined}>PR / handoff</RowLink>}
      <RowLink to={`/admin/tasks/${run.task.id}`}>Agent log</RowLink>
    </div>
  );
}

function RunReviewActions({
  projectId,
  run,
  onRequestChanges,
}: {
  projectId: string;
  run: ProjectCodingRun;
  onRequestChanges: () => void;
}) {
  const refreshRun = useRefreshProjectCodingRun(projectId);
  const markReviewed = useMarkProjectCodingRunReviewed(projectId);
  const cleanupRun = useCleanupProjectCodingRun(projectId);
  const disableLoop = useDisableProjectCodingRunLoop(projectId);
  const busy = refreshRun.isPending || markReviewed.isPending || cleanupRun.isPending || disableLoop.isPending;
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      <ActionButton
        label="Refresh"
        icon={<RefreshCcw size={13} />}
        size="small"
        variant="ghost"
        disabled={busy || run.review?.actions?.can_refresh === false}
        onPress={() => refreshRun.mutate(run.task.id)}
      />
      {run.review?.actions?.can_mark_reviewed && (
        <ActionButton
          label="Close on our side"
          icon={<Check size={13} />}
          size="small"
          variant="secondary"
          disabled={busy}
          onPress={() => markReviewed.mutate(run.task.id)}
        />
      )}
      {run.review?.actions?.can_request_changes && (
        <ActionButton
          label="Request changes"
          icon={<MessageSquarePlus size={13} />}
          size="small"
          variant="secondary"
          disabled={busy}
          onPress={onRequestChanges}
        />
      )}
      {run.review?.actions?.can_cleanup_instance && (
        <ActionButton
          label="Clean up"
          icon={<Trash2 size={13} />}
          size="small"
          variant="danger"
          disabled={busy}
          onPress={() => cleanupRun.mutate(run.task.id)}
        />
      )}
      {run.loop?.enabled && (
        <ActionButton
          label="Stop loop"
          icon={<Repeat2 size={13} />}
          size="small"
          variant="secondary"
          disabled={busy}
          onPress={() => disableLoop.mutate(run.task.id)}
        />
      )}
      <RunActionLinks run={run} />
    </div>
  );
}

function EmptyRunsAnchor({
  hasBlueprintSnapshot,
  onNewRun,
}: {
  hasBlueprintSnapshot: boolean;
  onNewRun: () => void;
}) {
  return (
    <Section
      title="Project work"
      description="No runs need review and no agents are currently working."
      action={<ActionButton label="New run" icon={<Play size={14} />} size="small" onPress={onNewRun} />}
    >
      <SettingsControlRow
        leading={<CheckCircle2 size={14} />}
        title="Nothing waiting"
        description="Start a new agent coding run when you have a ready story, bug, or follow-up."
        meta={hasBlueprintSnapshot ? <StatusBadge label="ready" variant="success" /> : <StatusBadge label="setup needed" variant="warning" />}
      />
    </Section>
  );
}

export function ProjectRunsSection({
  project,
  channels,
  receipts,
}: {
  project: Project;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
  receipts?: ProjectRunReceipt[];
}) {
  const { data: runs = [] } = useProjectCodingRuns(project.id);
  const { data: reviewBatches = [] } = useProjectCodingRunReviewBatches(project.id);
  const { data: reviewSessions = [] } = useProjectCodingRunReviewSessions(project.id);
  const createRun = useCreateProjectCodingRun(project.id);
  const createBlueprint = useCreateProjectBlueprintFromCurrent(project.id);
  const continueRun = useContinueProjectCodingRun(project.id);
  const markReviewedBatch = useMarkProjectCodingRunsReviewed(project.id);
  const createReviewSession = useCreateProjectCodingRunReviewSession(project.id);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [selectedRepoPath, setSelectedRepoPath] = useState("");
  const [request, setRequest] = useState("");
  const [createdRunId, setCreatedRunId] = useState<string | null>(null);
  const [showRunLauncher, setShowRunLauncher] = useState(false);
  const [runMachineTargetGrant, setRunMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [loopMaxIterations, setLoopMaxIterations] = useState(3);
  const [loopStopCondition, setLoopStopCondition] = useState("Stop when the requested work is implemented, verified, and ready for human review.");
  const [changeRunId, setChangeRunId] = useState<string | null>(null);
  const [changeFeedback, setChangeFeedback] = useState("");
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [batchMode, setBatchMode] = useState(false);
  const [reviewPrompt, setReviewPrompt] = useState("Review the selected PRs. Merge only accepted work to development, then mark those runs reviewed with links and blockers.");
  const [reviewMachineTargetGrant, setReviewMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [reviewTaskId, setReviewTaskId] = useState<string | null>(null);
  const visibleReceipts = useMemo(() => collapseProjectRunReceiptsForReview(receipts), [receipts]);

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
  const activeRuns = useMemo(() => runs.filter(isActiveCodingRun), [runs]);
  const activeReviewSessions = useMemo(() => reviewSessions.filter(isActiveReviewSession), [reviewSessions]);
  const historicalReviewSessions = useMemo(() => reviewSessions.filter((session) => !isActiveReviewSession(session)), [reviewSessions]);
  const createdRun = runs.find((run) => run.id === createdRunId);
  const changeRun = runs.find((run) => run.id === changeRunId);
  const selectedRuns = runs.filter((run) => selectedRunIds.includes(run.id));
  const selectedTaskIds = selectedRuns.map((run) => run.task.id);
  const reviewQueueRuns = useMemo(() => {
    return runs
      .filter(isHumanReviewQueueRun)
      .sort((a, b) => {
        const left = a.review_queue_priority ?? 99;
        const right = b.review_queue_priority ?? 99;
        if (left !== right) return left - right;
        return String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""));
      });
  }, [runs]);
  const launchBatchGroups = useMemo(() => {
    const groups = new Map<string, ProjectCodingRun[]>();
    for (const run of runs) {
      if (!run.launch_batch_id) continue;
      const current = groups.get(run.launch_batch_id) ?? [];
      current.push(run);
      groups.set(run.launch_batch_id, current);
    }
    return Array.from(groups.entries())
      .map(([id, batchRuns]) => ({ id, runs: batchRuns }))
      .filter((group) => group.runs.length > 1)
      .sort((a, b) => String(b.runs[0]?.created_at || "").localeCompare(String(a.runs[0]?.created_at || "")));
  }, [runs]);
  const batchBusy = markReviewedBatch.isPending || createReviewSession.isPending;
  const launchedReviewRuns = reviewTaskId ? selectedRuns : [];
  const toggleRun = (runId: string) => {
    setSelectedRunIds((current) => (
      current.includes(runId)
        ? current.filter((id) => id !== runId)
        : [...current, runId]
    ));
  };
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
          setCreatedRunId(run.id);
          setRequest("");
        },
      },
    );
  };
  const submitChanges = () => {
    if (!changeRun || continueRun.isPending) return;
    continueRun.mutate(
      { taskId: changeRun.task.id, feedback: changeFeedback.trim() },
      {
        onSuccess: () => {
          setChangeRunId(null);
          setChangeFeedback("");
        },
      },
    );
  };
  const markSelectedReviewed = () => {
    if (selectedTaskIds.length === 0 || batchBusy) return;
    markReviewedBatch.mutate(
      { task_ids: selectedTaskIds, note: "Batch marked reviewed from Project Runs." },
      { onSuccess: () => setSelectedRunIds([]) },
    );
  };
  const launchReviewSession = () => {
    if (!selectedChannel || selectedTaskIds.length === 0 || batchBusy) return;
    createReviewSession.mutate(
      {
        channel_id: selectedChannel.id,
        task_ids: selectedTaskIds,
        prompt: reviewPrompt.trim(),
        merge_method: "squash",
        machine_target_grant: reviewMachineTargetGrant,
      },
      {
        onSuccess: (task) => {
          setReviewTaskId(task.id);
        },
      },
    );
  };
  const launchReviewForBatch = (batchRuns: ProjectCodingRun[]) => {
    if (!selectedChannel || batchRuns.length === 0 || batchBusy) return;
    const taskIds = batchRuns.map((run) => run.task.id);
    const batchId = batchRuns[0]?.launch_batch_id;
    setSelectedRunIds(batchRuns.map((run) => run.id));
    createReviewSession.mutate(
      {
        channel_id: selectedChannel.id,
        task_ids: taskIds,
        prompt: `${reviewPrompt.trim()}\n\nReview launch batch ${batchId}. Keep finalization provenance linked to this batch.`,
        merge_method: "squash",
        machine_target_grant: reviewMachineTargetGrant,
      },
      {
        onSuccess: (task) => {
          setReviewTaskId(task.id);
        },
      },
    );
  };
  const launchReviewForRuns = (batchRuns: ProjectCodingRun[], promptSuffix: string) => {
    if (!selectedChannel || batchRuns.length === 0 || batchBusy) return;
    const taskIds = batchRuns.map((run) => run.task.id);
    setSelectedRunIds(batchRuns.map((run) => run.id));
    createReviewSession.mutate(
      {
        channel_id: selectedChannel.id,
        task_ids: taskIds,
        prompt: `${reviewPrompt.trim()}\n\n${promptSuffix}`,
        merge_method: "squash",
        machine_target_grant: reviewMachineTargetGrant,
      },
      {
        onSuccess: (task) => {
          setReviewTaskId(task.id);
        },
      },
    );
  };
  const launchReviewForInboxBatch = (batch: ProjectCodingRunReviewBatch) => {
    if (!selectedChannel || !batch.task_ids?.length || batchBusy) return;
    setSelectedRunIds(batch.run_ids ?? []);
    createReviewSession.mutate(
      {
        channel_id: selectedChannel.id,
        task_ids: batch.task_ids,
        prompt: `${reviewPrompt.trim()}\n\nReview launch batch ${batch.id}. Keep finalization provenance linked to this batch.`,
        merge_method: "squash",
        machine_target_grant: reviewMachineTargetGrant,
      },
      {
        onSuccess: (task) => {
          setReviewTaskId(task.id);
        },
      },
    );
  };

  useEffect(() => {
    const liveIds = new Set(runs.map((run) => run.id));
    setSelectedRunIds((current) => {
      const next = current.filter((id) => liveIds.has(id));
      return next.length === current.length ? current : next;
    });
  }, [runs]);

  return (
    <div data-testid="project-workspace-runs" className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
      {reviewQueueRuns.length > 0 ? (
      <Section title="Needs your review" description="Open the review page first. Ask an agent to review only when you want a separate visible review task.">
        <div className="flex flex-col gap-2">
          {reviewQueueRuns.map((run) => (
              <SettingsControlRow
                key={run.id}
                leading={<GitMerge size={14} />}
                title={run.request || run.task.title || "Project coding run"}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span>{reviewQueueDescription(run)}</span>
                    <span className="truncate text-[11px] text-text-dim">
                      Evidence: {evidenceSummary(run)}
                    </span>
                    {run.branch && (
                      <span className="truncate font-mono text-[11px] text-text-dim">{run.branch}</span>
                    )}
                    {run.launch_batch_id && (
                      <span className="truncate text-[11px] text-text-dim">Launch batch: {shortBatchId(run.launch_batch_id)}</span>
                    )}
                    {lineageLine(run) && (
                      <span className="truncate text-[11px] text-text-dim">Continuation: {lineageLine(run)}</span>
                    )}
                    {loopLine(run) && (
                      <span className="truncate text-[11px] text-text-dim">{loopLine(run)}</span>
                    )}
                    {reviewAgentLine(run) && (
                      <span className="truncate text-[11px] font-semibold text-text-muted">{reviewAgentLine(run)}</span>
                    )}
                  </span>
                }
                meta={<StatusBadge label={reviewQueueLabel(reviewQueueState(run))} variant={statusTone(reviewQueueState(run))} />}
                action={
                  <div className="flex flex-wrap justify-end gap-1">
                    <RowLink to={`/admin/projects/${run.project_id}/runs/${run.task.id}`}>Open review page</RowLink>
                    {isAgentReviewRunning(run) && reviewAgentTaskId(run) ? (
                      <RowLink to={`/admin/tasks/${reviewAgentTaskId(run)}`}>Review agent log</RowLink>
                    ) : (
                      <ActionButton
                        label={createReviewSession.isPending ? "Starting" : "Ask agent to review"}
                        icon={<GitMerge size={13} />}
                        size="small"
                        variant="secondary"
                        disabled={!selectedChannel || batchBusy || isAgentReviewRunning(run)}
                        onPress={() => launchReviewForRuns([run], `Review Project coding run ${run.task.id}. Preserve receipt, screenshot, PR, and follow-up provenance.`)}
                      />
                    )}
                    {(run.review?.handoff_url || run.receipt?.handoff_url) && <RowLink href={run.review?.handoff_url || run.receipt?.handoff_url || undefined}>PR / handoff</RowLink>}
                    <RowLink to={`/admin/tasks/${run.task.id}`}>Agent log</RowLink>
                  </div>
                }
              />
            ))}
          {reviewBatches.length > 0 && (
            <div className="mt-2 flex flex-col gap-2">
              <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">Batch review shortcuts</div>
              {reviewBatches.slice(0, 4).map((batch) => (
                <SettingsControlRow
                  key={batch.id}
                  leading={<GitMerge size={14} />}
                  title={batch.summary?.title || `Launch batch ${shortBatchId(batch.id)}`}
                  description={
                    <span className="flex min-w-0 flex-col gap-0.5">
                    <span>
                      Batch {shortBatchId(batch.id)} · {batch.run_count} run{batch.run_count === 1 ? "" : "s"} · {batchStatusLine(batch)}
                    </span>
                    <span className="truncate text-[11px] text-text-dim">
                      Sources: {batchSourceLine(batch)}
                    </span>
                    <span className="truncate text-[11px] text-text-dim">
                      Evidence: {batchEvidenceLine(batch)} · ready {batch.summary?.ready_count ?? 0} · unreviewed {batch.summary?.unreviewed_count ?? 0}
                    </span>
                    {batch.active_review_task?.task_id && (
                      <span className="truncate text-[11px] text-text-dim">
                        Active review: {String(batch.active_review_task.task_id).slice(0, 8)} · {batch.active_review_task.status}
                      </span>
                    )}
                    {!batch.active_review_task && batch.latest_review_task?.task_id && (
                      <span className="truncate text-[11px] text-text-dim">
                        Latest review: {String(batch.latest_review_task.task_id).slice(0, 8)} · {batch.latest_review_task.status}
                      </span>
                    )}
                    </span>
                  }
                  meta={<StatusBadge label={batch.status} variant={statusTone(batch.status)} />}
                  action={
                    <div className="flex flex-wrap justify-end gap-1">
                      <ActionButton
                        label="Select batch"
                        size="small"
                        variant="ghost"
                        disabled={batchBusy}
                        onPress={() => setSelectedRunIds(batch.run_ids ?? [])}
                      />
                      {batch.active_review_task?.task_id ? (
                        <RowLink to={`/admin/tasks/${batch.active_review_task.task_id}`}>Review agent log</RowLink>
                      ) : (
                        <ActionButton
                          label={createReviewSession.isPending ? "Starting" : "Ask agent to review batch"}
                          icon={<GitMerge size={13} />}
                          size="small"
                          variant="secondary"
                          disabled={!selectedChannel || batchBusy || !batch.actions?.can_start_review}
                          onPress={() => launchReviewForInboxBatch(batch)}
                        />
                      )}
                    </div>
                  }
                />
              ))}
            </div>
          )}
        </div>
      </Section>
      ) : activeRuns.length === 0 && activeReviewSessions.length === 0 ? (
        <EmptyRunsAnchor
          hasBlueprintSnapshot={hasBlueprintSnapshot}
          onNewRun={() => setShowRunLauncher(true)}
        />
      ) : null}

      {(activeRuns.length > 0 || activeReviewSessions.length > 0) && (
        <Section
          title="Running now"
          description="Live implementation and review agents. Open the run page for context, or the agent log for the raw session."
        >
          <div className="flex flex-col gap-2">
            {activeRuns.map((run) => (
              <SettingsControlRow
                key={run.id}
                leading={<Play size={14} />}
                title={runTitle(run)}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate text-[11px] text-text-dim">{activeRunLine(run)}</span>
                    <span className="truncate text-[11px] text-text-dim">
                      Started {formatRunTime(run.created_at)} · {run.task.bot_id}
                    </span>
                    {loopLine(run) && <span className="truncate text-[11px] text-text-dim">{loopLine(run)}</span>}
                  </span>
                }
                meta={<StatusBadge label={run.task.status || run.status} variant={statusTone(run.task.status || run.status)} />}
                action={<RunActionLinks run={run} />}
              />
            ))}
            {activeReviewSessions.map((session) => (
              <SettingsControlRow
                key={session.id}
                leading={<GitMerge size={14} />}
                title={session.title || "Review agent running"}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate text-[11px] text-text-dim">
                      Review agent · {session.run_count} run{session.run_count === 1 ? "" : "s"} · latest {formatRunTime(session.latest_activity_at || session.created_at)}
                    </span>
                    {session.latest_summary && <span className="truncate text-[11px] text-text-dim">{session.latest_summary}</span>}
                    {(session.selected_run_ids?.length ?? 0) > 0 && (
                      <span className="truncate text-[11px] text-text-dim">Selected runs: {session.selected_run_ids?.map((id) => id.slice(0, 8)).join(", ")}</span>
                    )}
                  </span>
                }
                meta={<StatusBadge label={session.task_status || session.status} variant={statusTone(session.task_status || session.status)} />}
                action={
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    <ActionButton
                      label="Select reviewed runs"
                      size="small"
                      variant="ghost"
                      disabled={batchBusy || !(session.selected_run_ids?.length)}
                      onPress={() => setSelectedRunIds(session.selected_run_ids ?? [])}
                    />
                    <RowLink to={`/admin/tasks/${session.task_id}`}>Review agent log</RowLink>
                  </div>
                }
              />
            ))}
          </div>
        </Section>
      )}

      {reviewTaskId && (
        <Section
          title="Review agent started"
          description="A normal task was created for the selected review. Open it to watch or steer the agent."
        >
          <SettingsControlRow
            leading={<GitMerge size={14} />}
            title="Review agent task created"
            description={
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate font-mono text-[11px] text-text-dim">{reviewTaskId}</span>
                <span className="truncate text-[11px] text-text-dim">
                  {launchedReviewRuns.length} selected run{launchedReviewRuns.length === 1 ? "" : "s"}
                  {selectedChannel ? ` · ${selectedChannel.name}` : ""}
                </span>
                {launchedReviewRuns[0] && (
                  <span className="truncate text-[11px] text-text-dim">First run: {runTitle(launchedReviewRuns[0])}</span>
                )}
              </span>
            }
            meta={<StatusBadge label="started" variant="info" />}
            action={
              <div className="flex flex-wrap items-center justify-end gap-1">
                {launchedReviewRuns[0] && <RowLink to={`/admin/projects/${project.id}/runs/${launchedReviewRuns[0].task.id}`}>Open review page</RowLink>}
                <RowLink to={`/admin/tasks/${reviewTaskId}`}>Review agent log</RowLink>
              </div>
            }
          />
        </Section>
      )}

      <Section
        title="Start new work"
        description="Launch a new implementation agent only when you are ready to start more work."
        action={
          <ActionButton
            label={!showRunLauncher ? "New run" : createRun.isPending ? "Starting" : "Start run"}
            icon={<Play size={14} />}
            disabled={showRunLauncher && (!selectedChannel || !hasBlueprintSnapshot || createRun.isPending)}
            onPress={() => {
              if (!showRunLauncher) {
                setShowRunLauncher(true);
                return;
              }
              startRun();
            }}
          />
        }
      >
        {showRunLauncher ? (
          <>
        <div className="grid gap-3 md:grid-cols-[minmax(240px,0.85fr)_minmax(0,1.15fr)]">
          <FormRow label="Channel">
            <SelectInput
              value={selectedChannelId}
              onChange={(value) => setSelectedChannelId(value)}
              options={
                channels && channels.length > 0
                  ? channels.map((channel) => ({
                    label: `${channel.name} · ${channel.bot_id}`,
                    value: channel.id,
                  }))
                  : [{ label: "Attach a Project channel first", value: "" }]
              }
            />
          </FormRow>
          {blueprintRepos.length > 1 && (
            <FormRow label="Repository" description="The declared repo this run should branch, test, and hand off.">
              <SelectInput
                value={selectedRepoPath}
                onChange={(value) => setSelectedRepoPath(value)}
                options={blueprintRepos}
              />
            </FormRow>
          )}
          <FormRow label="Project request" description="A concise bug, feature, or review task for the selected Project channel.">
            <PromptEditor
              value={request}
              onChange={setRequest}
              label="Run request"
              placeholder="Implement the next issue, run tests, capture e2e screenshots, and publish a handoff receipt..."
              rows={5}
              fieldType="task_prompt"
              generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
            />
          </FormRow>
        </div>
        <div className="mt-3">
          <ExecutionAccessControl
            value={runMachineTargetGrant}
            onChange={setRunMachineTargetGrant}
            testId="project-run-execution-access"
          />
        </div>
        <div className="mt-3 rounded-md bg-surface-raised/30 p-3">
          <label className="flex items-center gap-2 text-[12px] font-semibold text-text">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-input-border bg-input"
              checked={loopEnabled}
              onChange={(event) => setLoopEnabled(event.target.checked)}
            />
            Bounded loop
          </label>
          {loopEnabled && (
            <div className="mt-3 grid gap-3 md:grid-cols-[160px_minmax(0,1fr)]">
              <FormRow label="Max iterations">
                <SelectInput
                  value={String(loopMaxIterations)}
                  onChange={(value) => setLoopMaxIterations(Number(value))}
                  options={[2, 3, 4, 5, 6, 7, 8].map((value) => ({ label: String(value), value: String(value) }))}
                />
              </FormRow>
              <FormRow label="Stop condition">
                <textarea
                  value={loopStopCondition}
                  onChange={(event) => setLoopStopCondition(event.target.value)}
                  rows={2}
                  className="min-h-[58px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] text-text outline-none focus:border-accent"
                />
              </FormRow>
            </div>
          )}
        </div>
        {!hasBlueprintSnapshot && (
          <div className="mt-3">
            <SettingsControlRow
              leading={<AlertTriangle size={14} />}
              title="Blueprint recipe required"
              description="Create a durable Blueprint from this Project before launching isolated coding runs."
              meta={<StatusBadge label="setup needed" variant="warning" />}
              action={
                <ActionButton
                  label={createBlueprint.isPending ? "Creating" : "Create Blueprint"}
                  icon={<FileText size={13} />}
                  size="small"
                  disabled={createBlueprint.isPending}
                  onPress={() => createBlueprint.mutate({ apply_to_project: true })}
                />
              }
            />
          </div>
        )}
        {createdRun && (
          <div className="mt-3">
            <SettingsControlRow
              leading={<CheckCircle2 size={14} />}
              title="Coding run created"
              description={
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="truncate font-mono text-[11px] text-text-dim">{createdRun.branch}</span>
                  <span>{createdRun.base_branch ? `Base ${createdRun.base_branch}` : "Base repository default"}</span>
                  {executionAccessLine(createdRun.task.machine_target_grant) && (
                    <span>{executionAccessLine(createdRun.task.machine_target_grant)}</span>
                  )}
                </span>
              }
              meta={<StatusBadge label={createdRun.status} variant={statusTone(createdRun.status)} />}
              action={<RunActionLinks run={createdRun} />}
            />
          </div>
        )}
        {createRun.error && (
          <div className="mt-3">
            <SettingsControlRow
              leading={<AlertTriangle size={14} />}
              title="Run did not start"
              description={createRun.error instanceof Error ? createRun.error.message : "The coding-run request failed."}
              meta={<StatusBadge label="failed" variant="danger" />}
            />
          </div>
        )}
          </>
        ) : (
          <SettingsControlRow
            leading={<Play size={14} />}
            title="Start a new agent coding run"
            description="Use this for fresh work. Existing active runs, human review, and agent review sessions stay visible on the page."
            meta={hasBlueprintSnapshot ? <StatusBadge label="ready" variant="success" /> : <StatusBadge label="setup needed" variant="warning" />}
            action={
              <ActionButton
                label="New run"
                icon={<Play size={13} />}
                size="small"
                variant="secondary"
                onPress={() => setShowRunLauncher(true)}
              />
            }
          />
        )}
      </Section>

      {historicalReviewSessions.length > 0 && (
        <ReviewSessionsSection
          sessions={historicalReviewSessions}
          disabled={batchBusy}
          onSelectRuns={(runIds) => setSelectedRunIds(runIds)}
        />
      )}

      <ProjectScheduledReviewsSection project={project} channels={channels} selectedChannelId={selectedChannelId} />

      <Section
        title="Run history"
        description="Audit trail for every Project coding run. Batch controls stay hidden until you need them."
        action={
          runs.length > 0 ? (
            <ActionButton
              label={batchMode ? "Done selecting" : "Batch tools"}
              icon={<GitMerge size={13} />}
              size="small"
              variant="secondary"
              onPress={() => {
                setBatchMode((current) => !current);
                if (batchMode) setSelectedRunIds([]);
              }}
            />
          ) : undefined
        }
      >
        {batchMode && (
          <div className="mb-3 grid gap-3 rounded-md bg-surface-raised/30 p-3 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="flex min-w-0 flex-col gap-2">
              <label className="inline-flex items-center gap-2 text-[12px] font-semibold text-text">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-input-border bg-input"
                  checked={selectedRunIds.length > 0 && selectedRunIds.length === runs.length}
                  ref={(input) => {
                    if (input) input.indeterminate = selectedRunIds.length > 0 && selectedRunIds.length < runs.length;
                  }}
                  onChange={(event) => setSelectedRunIds(event.target.checked ? runs.map((run) => run.id) : [])}
                />
                {selectedRunIds.length === 0 ? "Select runs to review together" : `${selectedRunIds.length} selected`}
              </label>
              {selectedRunIds.length > 0 && (
                <>
                  <PromptEditor
                    value={reviewPrompt}
                    onChange={setReviewPrompt}
                    label="Agent review prompt"
                    rows={3}
                    fieldType="task_prompt"
                    generateContext={`Project: ${project.name}. Selected runs: ${selectedRunIds.length}`}
                  />
                  <ExecutionAccessControl
                    value={reviewMachineTargetGrant}
                    onChange={setReviewMachineTargetGrant}
                    testId="project-review-execution-access"
                  />
                </>
              )}
              {launchBatchGroups.length > 0 && (
                <div className="flex flex-col gap-1 pt-1">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">Launch batches</span>
                  {launchBatchGroups.slice(0, 4).map((group) => (
                    <div key={group.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-raised/40 px-2.5 py-2">
                      <span className="min-w-0 truncate text-[12px] text-text-muted">
                        Batch {shortBatchId(group.id)} · {group.runs.length} run{group.runs.length === 1 ? "" : "s"}
                      </span>
                      <div className="flex items-center gap-1">
                        <ActionButton
                          label="Select"
                          size="small"
                          variant="ghost"
                          disabled={batchBusy}
                          onPress={() => setSelectedRunIds(group.runs.map((run) => run.id))}
                        />
                        <ActionButton
                          label={createReviewSession.isPending ? "Starting" : "Ask agent to review batch"}
                          icon={<GitMerge size={13} />}
                          size="small"
                          variant="secondary"
                          disabled={!selectedChannel || batchBusy}
                          onPress={() => launchReviewForBatch(group.runs)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-start justify-end gap-1">
              <ActionButton
                label="Close on our side"
                icon={<Check size={13} />}
                size="small"
                variant="secondary"
                disabled={selectedTaskIds.length === 0 || batchBusy}
                onPress={markSelectedReviewed}
              />
              <ActionButton
                label={createReviewSession.isPending ? "Starting" : "Ask agent to review"}
                icon={<GitMerge size={13} />}
                size="small"
                disabled={!selectedChannel || selectedTaskIds.length === 0 || batchBusy}
                onPress={launchReviewSession}
              />
            </div>
          </div>
        )}
        <div className="flex flex-col gap-2">
          {runs.length === 0 ? (
            <EmptyState message="No Project coding runs have been started yet." />
          ) : (
            runs.map((run) => (
              <div key={run.id} className="flex flex-col gap-2">
                <SettingsControlRow
                  leading={
                    <span className="inline-flex items-center gap-2">
                      {batchMode && (
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-input-border bg-input"
                          checked={selectedRunIds.includes(run.id)}
                          onChange={() => toggleRun(run.id)}
                          aria-label={`Select ${run.request || run.task.title || "Project coding run"}`}
                        />
                      )}
                      <GitBranch size={14} />
                    </span>
                  }
                  title={run.request || run.task.title || "Project coding run"}
                  description={
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="truncate font-mono text-[11px] text-text-dim">{run.branch ?? "No branch recorded"}</span>
                      <span>
                        {formatRunTime(run.updated_at ?? run.created_at)}
                        {run.base_branch ? ` · base ${run.base_branch}` : ""}
                        {run.repo?.path ? ` · ${run.repo.path}` : ""}
                      </span>
                      <span className="truncate text-[11px] text-text-dim">
                        Review: {reviewStatusLabel(run)} · Evidence: {evidenceSummary(run)}
                      </span>
                      {run.launch_batch_id && (
                        <span className="truncate text-[11px] text-text-dim">Launch batch: {shortBatchId(run.launch_batch_id)}</span>
                      )}
                      {lineageLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">Continuation: {lineageLine(run)}</span>
                      )}
                      {loopLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{loopLine(run)}</span>
                      )}
                      {reviewLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{reviewLine(run)}</span>
                      )}
                      {executionAccessLine(run.task.machine_target_grant) && (
                        <span className="truncate text-[11px] text-text-dim">Execution access: {executionAccessLine(run.task.machine_target_grant)}</span>
                      )}
                      {workSurfaceLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{workSurfaceLine(run)}</span>
                      )}
                      {dependencyStackLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{dependencyStackLine(run)}</span>
                      )}
                      {devTargetsLine(run.dev_targets) && (
                        <span className="truncate text-[11px] text-text-dim">Dev targets: {devTargetsLine(run.dev_targets)}</span>
                      )}
                      <span className="truncate text-[11px] text-text-dim">
                        {handoffProgressSummary(run) ? `Progress: ${handoffProgressSummary(run)}` : `Activity: ${activitySummary(run)}`}
                      </span>
                      {run.receipt && (
                        <span className="truncate text-[11px] text-text-dim">
                          Receipt: {run.receipt.summary}
                        </span>
                      )}
                    </span>
                  }
                  meta={<StatusBadge label={reviewStatusLabel(run)} variant={statusTone(reviewStatusLabel(run))} />}
                  action={
                    batchMode ? (
                      <RunActionLinks run={run} />
                    ) : (
                      <RunReviewActions projectId={project.id} run={run} onRequestChanges={() => {
                        setChangeRunId(run.id);
                        setChangeFeedback(run.continuation_feedback || "");
                      }} />
                    )
                  }
                />
                {changeRunId === run.id && (
                  <div className="rounded-md bg-surface-raised/40 px-3 py-3">
                    <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">
                      Reviewer feedback
                    </label>
                    <textarea
                      value={changeFeedback}
                      onChange={(event) => setChangeFeedback(event.target.value)}
                      rows={3}
                      className="min-h-[84px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] text-text outline-none focus:border-accent"
                      placeholder="Describe the changes needed on this PR..."
                    />
                    <div className="mt-2 flex items-center justify-end gap-1">
                      <ActionButton
                        label="Cancel"
                        size="small"
                        variant="ghost"
                        disabled={continueRun.isPending}
                        onPress={() => {
                          setChangeRunId(null);
                          setChangeFeedback("");
                        }}
                      />
                      <ActionButton
                        label={continueRun.isPending ? "Starting" : "Start follow-up"}
                        icon={<MessageSquarePlus size={13} />}
                        size="small"
                        disabled={continueRun.isPending}
                        onPress={submitChanges}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </Section>

      <Section title="Run Receipts" description="Implementation summaries, tests, screenshots, and handoff links published by coding agents.">
        <div className="flex flex-col gap-2">
          {visibleReceipts.length === 0 ? (
            <EmptyState message="No coding-run receipts have been published for this Project." />
          ) : (
            visibleReceipts.map((receipt) => (
              <SettingsControlRow
                key={receipt.id}
                leading={<FileText size={14} />}
                title={receipt.summary}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span>{formatRunTime(receipt.created_at)} · {receipt.bot_id ?? "unknown bot"}</span>
                    {(receipt.duplicate_count ?? 1) > 1 && (
                      <span className="text-[11px] text-text-dim">{receipt.duplicate_count} receipt updates collapsed</span>
                    )}
                    <span className="truncate font-mono text-[11px] text-text-dim">Files: {compactEvidence(receipt.changed_files)}</span>
                    <span className="truncate text-[11px] text-text-dim">Tests: {compactEvidence(receipt.tests)}</span>
                    <span className="truncate text-[11px] text-text-dim">Screenshots: {compactEvidence(receipt.screenshots)}</span>
                    <span className="truncate text-[11px] text-text-dim">Dev targets: {devTargetsLine(receipt.dev_targets) || "none reported"}</span>
                  </span>
                }
                meta={<StatusBadge label={receipt.status} variant={statusTone(receipt.status)} />}
                action={
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    {receipt.task_id && <RowLink to={`/admin/projects/${receipt.project_id}/runs/${receipt.task_id}`}>Open review page</RowLink>}
                    {receipt.handoff_url && <RowLink href={receipt.handoff_url}>PR / handoff</RowLink>}
                  </div>
                }
              />
            ))
          )}
        </div>
      </Section>
    </div>
  );
}
