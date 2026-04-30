import { Link } from "react-router-dom";
import { AlertTriangle, Check, CheckCircle2, ExternalLink, FileText, GitBranch, MessageSquarePlus, Play, RefreshCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  useCleanupProjectCodingRun,
  useContinueProjectCodingRun,
  useCreateProjectCodingRun,
  useMarkProjectCodingRunReviewed,
  useProjectCodingRuns,
  useRefreshProjectCodingRun,
} from "@/src/api/hooks/useProjects";
import { FormRow, Section, SelectInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { ActionButton, EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { collapseProjectRunReceiptsForReview } from "@/src/lib/projectRunReceipts";
import type { Channel, Project, ProjectCodingRun, ProjectRunReceipt } from "@/src/types/api";

function RowLink({ to, href, children }: { to?: string; href?: string; children: React.ReactNode }) {
  const className = "inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text";
  const content = (
    <>
      <ExternalLink size={13} />
      {children}
    </>
  );
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className}>
        {content}
      </a>
    );
  }
  return (
    <Link to={to ?? "#"} className={className}>
      {content}
    </Link>
  );
}

function formatRunTime(value?: string | null) {
  if (!value) return "No timestamp";
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "completed" || status === "complete" || status === "reported" || status === "ready_for_review" || status === "reviewed") return "success";
  if (status === "pending" || status === "running" || status === "needs_review" || status === "blocked" || status === "pending_evidence") return "warning";
  if (status === "failed") return "danger";
  return "neutral";
}

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
    return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files`;
  }
  if (!run.receipt) return "No evidence receipt yet";
  return `${run.receipt.tests?.length ?? 0} tests · ${run.receipt.screenshots?.length ?? 0} screenshots · ${run.receipt.changed_files?.length ?? 0} files`;
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
  const createRun = useCreateProjectCodingRun(project.id);
  const continueRun = useContinueProjectCodingRun(project.id);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [request, setRequest] = useState("");
  const [createdRunId, setCreatedRunId] = useState<string | null>(null);
  const [changeRunId, setChangeRunId] = useState<string | null>(null);
  const [changeFeedback, setChangeFeedback] = useState("");
  const visibleReceipts = useMemo(() => collapseProjectRunReceiptsForReview(receipts), [receipts]);

  useEffect(() => {
    if (!selectedChannelId && channels && channels.length > 0) {
      setSelectedChannelId(channels[0].id);
    }
  }, [channels, selectedChannelId]);

  const selectedChannel = channels?.find((channel) => channel.id === selectedChannelId);
  const createdRun = runs.find((run) => run.id === createdRunId);
  const changeRun = runs.find((run) => run.id === changeRunId);
  const startRun = () => {
    if (!selectedChannel || createRun.isPending) return;
    createRun.mutate(
      { channel_id: selectedChannel.id, request: request.trim() },
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
        {createdRun && (
          <div className="mt-3">
            <SettingsControlRow
              leading={<CheckCircle2 size={14} />}
              title="Coding run created"
              description={
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="truncate font-mono text-[11px] text-text-dim">{createdRun.branch}</span>
                  <span>{createdRun.base_branch ? `Base ${createdRun.base_branch}` : "Base repository default"}</span>
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

      <Section title="Coding Runs" description="Review state, branch/PR handoff, evidence, and workspace cleanup for API-launched Project work.">
        <div className="flex flex-col gap-2">
          {runs.length === 0 ? (
            <EmptyState message="No Project coding runs have been started yet." />
          ) : (
            runs.map((run) => (
              <div key={run.id} className="flex flex-col gap-2">
                <SettingsControlRow
                  leading={<GitBranch size={14} />}
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
                      {lineageLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">Continuation: {lineageLine(run)}</span>
                      )}
                      {reviewLine(run) && (
                        <span className="truncate text-[11px] text-text-dim">{reviewLine(run)}</span>
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
