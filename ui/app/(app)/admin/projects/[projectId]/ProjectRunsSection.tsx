import { Link } from "react-router-dom";
import { AlertTriangle, Check, CheckCircle2, FileText, GitBranch, GitMerge, MessageSquarePlus, Play, RefreshCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  useCleanupProjectCodingRun,
  useContinueProjectCodingRun,
  useCreateProjectCodingRun,
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
import type { Channel, Project, ProjectCodingRun, ProjectCodingRunReviewBatch, ProjectRunReceipt } from "@/src/types/api";
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

function reviewLine(run: ProjectCodingRun) {
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

function dependencyStackLine(run: ProjectCodingRun) {
  const stack = run.dependency_stack;
  if (!stack?.configured) return null;
  const instance = stack.instance;
  if (!instance) return "Dependency stack: not prepared";
  const target = instance.source_path || instance.id;
  const envKeys = Object.keys(instance.env ?? {});
  return `Dependency stack: ${instance.status}${target ? ` · ${target}` : ""}${envKeys.length ? ` · env ${envKeys.length}` : ""}`;
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
  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {(run.review?.handoff_url || run.receipt?.handoff_url) && <RowLink href={run.review?.handoff_url || run.receipt?.handoff_url || undefined}>Handoff</RowLink>}
      <RowLink to={`/admin/tasks/${run.task.id}`}>Task</RowLink>
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
  const busy = refreshRun.isPending || markReviewed.isPending || cleanupRun.isPending;
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
          label="Reviewed"
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
      <RunActionLinks run={run} />
    </div>
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
  const continueRun = useContinueProjectCodingRun(project.id);
  const markReviewedBatch = useMarkProjectCodingRunsReviewed(project.id);
  const createReviewSession = useCreateProjectCodingRunReviewSession(project.id);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [request, setRequest] = useState("");
  const [createdRunId, setCreatedRunId] = useState<string | null>(null);
  const [runMachineTargetGrant, setRunMachineTargetGrant] = useState<MachineTargetGrant | null>(null);
  const [changeRunId, setChangeRunId] = useState<string | null>(null);
  const [changeFeedback, setChangeFeedback] = useState("");
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
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
  const createdRun = runs.find((run) => run.id === createdRunId);
  const changeRun = runs.find((run) => run.id === changeRunId);
  const selectedRuns = runs.filter((run) => selectedRunIds.includes(run.id));
  const selectedTaskIds = selectedRuns.map((run) => run.task.id);
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
  const toggleRun = (runId: string) => {
    setSelectedRunIds((current) => (
      current.includes(runId)
        ? current.filter((id) => id !== runId)
        : [...current, runId]
    ));
  };
  const startRun = () => {
    if (!selectedChannel || createRun.isPending) return;
    createRun.mutate(
      {
        channel_id: selectedChannel.id,
        request: request.trim(),
        machine_target_grant: runMachineTargetGrant,
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
      <Section
        title="Agent Coding Run"
        description="Start a Project-scoped implementation task with a fresh instance, guided branch handoff, runtime env, and review receipt."
        action={
          <ActionButton
            label={createRun.isPending ? "Starting" : "Start Run"}
            icon={<Play size={14} />}
            disabled={!selectedChannel || createRun.isPending}
            onPress={startRun}
          />
        }
      >
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
      </Section>

      <ProjectScheduledReviewsSection project={project} channels={channels} selectedChannelId={selectedChannelId} />

      <Section title="Review Inbox" description="Launch batches grouped for morning review, with readiness, evidence, source packs, and review-session links.">
        <div className="flex flex-col gap-2">
          {reviewBatches.length === 0 ? (
            <EmptyState message="No launched Work Pack batches are waiting for review." />
          ) : (
            reviewBatches.map((batch) => (
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
                      label="Select runs"
                      size="small"
                      variant="ghost"
                      disabled={batchBusy}
                      onPress={() => setSelectedRunIds(batch.run_ids ?? [])}
                    />
                    {batch.active_review_task?.task_id ? (
                      <RowLink to={`/admin/tasks/${batch.active_review_task.task_id}`}>Open review</RowLink>
                    ) : (
                      <ActionButton
                        label={createReviewSession.isPending ? "Starting" : "Start review"}
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
            ))
          )}
        </div>
      </Section>

      <ReviewSessionsSection
        sessions={reviewSessions}
        disabled={batchBusy}
        onSelectRuns={(runIds) => setSelectedRunIds(runIds)}
      />

      <Section title="Coding Runs" description="Review state, branch/PR handoff, evidence, and workspace cleanup for API-launched Project work.">
        {runs.length > 0 && (
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
                {selectedRunIds.length === 0 ? "Select coding runs" : `${selectedRunIds.length} selected`}
              </label>
              <PromptEditor
                value={reviewPrompt}
                onChange={setReviewPrompt}
                label="Review session prompt"
                rows={3}
                fieldType="task_prompt"
                generateContext={`Project: ${project.name}. Selected runs: ${selectedRunIds.length}`}
              />
              <ExecutionAccessControl
                value={reviewMachineTargetGrant}
                onChange={setReviewMachineTargetGrant}
                testId="project-review-execution-access"
              />
              {reviewTaskId && (
                <span className="text-[12px] text-text-muted">
                  Review session started: <Link className="font-mono text-accent" to={`/admin/tasks/${reviewTaskId}`}>{reviewTaskId.slice(0, 8)}</Link>
                </span>
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
                          label={createReviewSession.isPending ? "Starting" : "Review batch"}
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
                label="Mark reviewed"
                icon={<Check size={13} />}
                size="small"
                variant="secondary"
                disabled={selectedTaskIds.length === 0 || batchBusy}
                onPress={markSelectedReviewed}
              />
              <ActionButton
                label={createReviewSession.isPending ? "Starting" : "Start review"}
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
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-input-border bg-input"
                        checked={selectedRunIds.includes(run.id)}
                        onChange={() => toggleRun(run.id)}
                        aria-label={`Select ${run.request || run.task.title || "Project coding run"}`}
                      />
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
                      {reviewLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{reviewLine(run)}</span>
                      )}
                      {executionAccessLine(run.task.machine_target_grant) && (
                        <span className="truncate text-[11px] text-text-dim">Execution access: {executionAccessLine(run.task.machine_target_grant)}</span>
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
                  action={<RunReviewActions projectId={project.id} run={run} onRequestChanges={() => {
                    setChangeRunId(run.id);
                    setChangeFeedback(run.continuation_feedback || "");
                  }} />}
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
                action={receipt.handoff_url ? <RowLink href={receipt.handoff_url}>Handoff</RowLink> : undefined}
              />
            ))
          )}
        </div>
      </Section>
    </div>
  );
}
