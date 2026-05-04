import { AlertTriangle, CheckCircle2, ExternalLink, FileText, GitBranch, GitMerge, ListChecks, MessageSquarePlus, Monitor, Repeat2, ServerCog, TerminalSquare } from "lucide-react";
import type React from "react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useCancelProjectCodingRun, useContinueProjectCodingRun, useDisableProjectCodingRunLoop, useMarkProjectCodingRunReviewed, useProject, useProjectCodingRun } from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Section } from "@/src/components/shared/FormControls";
import { ActionButton, EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import type { ProjectCodingRun } from "@/src/types/api";
import { formatRunTime, RowLink, statusTone } from "../../ProjectRunControls";

function textValue(value: unknown, fallback = "Not reported") {
  if (value == null || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function itemTitle(item: unknown, fallback: string) {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const record = item as Record<string, any>;
    return String(record.path || record.file || record.command || record.name || record.label || record.url || record.status || fallback);
  }
  return fallback;
}

function itemDescription(item: unknown) {
  if (typeof item === "string") return null;
  if (!item || typeof item !== "object") return null;
  const record = item as Record<string, any>;
  const pieces = [
    record.summary,
    record.status ? `status ${record.status}` : null,
    record.exit_code != null ? `exit ${record.exit_code}` : null,
    record.viewport,
    record.notes,
  ].filter(Boolean);
  return pieces.length > 0 ? pieces.join(" · ") : JSON.stringify(record);
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[360px] overflow-auto rounded-md border border-border-subtle bg-input/60 p-3 text-[12px] leading-relaxed text-text-muted">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function EvidenceList({
  title,
  icon,
  values,
  empty,
}: {
  title: string;
  icon: React.ReactNode;
  values?: unknown[];
  empty: string;
}) {
  const rows = values ?? [];
  return (
    <Section title={title} description={`${rows.length} recorded`}>
      <div className="flex flex-col gap-2">
        {rows.length === 0 ? (
          <EmptyState message={empty} />
        ) : (
          rows.map((item, index) => (
            <SettingsControlRow
              key={`${title}-${index}`}
              leading={icon}
              title={itemTitle(item, `${title} ${index + 1}`)}
              description={itemDescription(item)}
              meta={typeof item === "object" && item && "status" in item ? <StatusBadge label={String((item as Record<string, any>).status)} variant={statusTone(String((item as Record<string, any>).status))} /> : undefined}
              action={typeof item === "object" && item && (item as Record<string, any>).url ? <RowLink href={String((item as Record<string, any>).url)}>Open</RowLink> : undefined}
            />
          ))
        )}
      </div>
    </Section>
  );
}

function reviewStatus(run: ProjectCodingRun) {
  return run.lifecycle?.phase || run.review?.status || run.status;
}

function problemTitle(run: ProjectCodingRun) {
  return run.task.title || run.request || "Project coding run";
}

function lifecycleHeadline(run: ProjectCodingRun) {
  return run.lifecycle?.headline || problemTitle(run);
}

function lifecycleNextAction(run: ProjectCodingRun) {
  return run.lifecycle?.next_action || run.review_next_action || "Review evidence, merge or request changes, then close the run.";
}

function problemSummary(run: ProjectCodingRun) {
  return run.request || run.receipt?.summary || "No problem statement was recorded for this run.";
}

function sourceLine(run: ProjectCodingRun) {
  const artifact = run.source_artifact;
  const pieces = [
    artifact?.path ? `artifact ${artifact.path}${artifact.section ? `#${artifact.section}` : ""}` : null,
    run.launch_batch_id ? `batch ${run.launch_batch_id}` : null,
    run.task.channel_id ? `channel ${String(run.task.channel_id).slice(0, 8)}` : null,
    run.task.session_id ? `session ${String(run.task.session_id).slice(0, 8)}` : null,
  ].filter(Boolean);
  return pieces.join(" · ") || "Started directly from a Project coding-run request";
}

function isTerminalReviewed(run: ProjectCodingRun) {
  return Boolean(run.review?.reviewed || run.review_queue_state === "reviewed");
}

function prLine(run: ProjectCodingRun) {
  const pr = run.review?.pr;
  if (!pr) return "No PR status recorded";
  return [
    pr.state ? `state ${pr.state}` : null,
    pr.draft != null ? (pr.draft ? "draft" : "ready") : null,
    pr.merge_state ? `merge ${pr.merge_state}` : null,
    pr.review_decision ? `review ${pr.review_decision}` : null,
    pr.checks_status ? `checks ${pr.checks_status}` : null,
  ].filter(Boolean).join(" · ") || "PR linked";
}

function workSurfaceTitle(run: ProjectCodingRun) {
  const surface = run.work_surface;
  if (!surface) return "Work surface not reported";
  if (surface.kind === "project_instance") {
    if (surface.isolation === "pending") return "Fresh Project instance pending";
    return "Fresh Project instance";
  }
  if (surface.kind === "project") return "Shared Project root";
  return surface.kind ? `Work surface ${surface.kind}` : "Work surface not reported";
}

function workSurfaceLine(run: ProjectCodingRun) {
  const surface = run.work_surface;
  if (!surface) return "No work-surface payload was returned for this run";
  const pieces = [
    surface.display_path || (surface.root_path ? `/${surface.root_path}` : null),
    surface.status ? `status ${surface.status}` : null,
    surface.expected === "fresh_project_instance" ? "fresh required" : "shared root",
    surface.expires_at ? `expires ${formatRunTime(surface.expires_at)}` : null,
  ].filter(Boolean);
  return surface.blocker || pieces.join(" · ") || "No work-surface details reported";
}

function recoveryTitle(run: ProjectCodingRun) {
  if (run.latest_continuation?.task_id || run.review?.recovery?.latest_continuation_id) return "Follow-up run created";
  if (run.review?.recovery?.can_continue || run.review?.actions?.can_continue) return "Follow-up run available";
  if (run.review?.reviewed) return "Recovery closed";
  if (run.review?.recovery?.blocker) return "Recovery blocked";
  return "Recovery status";
}

function recoveryLine(run: ProjectCodingRun) {
  const recovery = run.review?.recovery;
  if (recovery?.blocker) return recovery.blocker;
  if (run.latest_continuation?.task_id || recovery?.latest_continuation_id) return "A follow-up run has already been created from this run.";
  if (run.review?.actions?.can_continue || recovery?.can_continue) return "Create a follow-up run with reviewer feedback, preserving the original branch/repo/runtime context.";
  return "No recovery action is currently available for this run.";
}

function loopLine(run: ProjectCodingRun) {
  const loop = run.loop;
  if (!loop?.enabled) return "Loop not enabled for this run.";
  return [
    `state ${loop.state || "waiting"}`,
    `iteration ${loop.iteration || 1}/${loop.max_iterations || 1}`,
    loop.latest_decision ? `decision ${loop.latest_decision}` : null,
    loop.stop_reason ? `stop ${loop.stop_reason.replaceAll("_", " ")}` : null,
  ].filter(Boolean).join(" · ");
}

function reviewAgentTaskId(run: ProjectCodingRun) {
  return run.review?.review_task_id || null;
}

export default function ProjectRunDetail() {
  const { projectId, taskId } = useParams<{ projectId: string; taskId: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data: run, isLoading: runLoading, error } = useProjectCodingRun(projectId, taskId);
  const continueRun = useContinueProjectCodingRun(projectId);
  const cancelRun = useCancelProjectCodingRun(projectId);
  const markReviewed = useMarkProjectCodingRunReviewed(projectId);
  const disableLoop = useDisableProjectCodingRunLoop(projectId);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [createdFollowUp, setCreatedFollowUp] = useState<ProjectCodingRun | null>(null);

  if (projectLoading || runLoading) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }

  if (!project || !run) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-surface">
        <PageHeader variant="detail" chrome="flow" title="Project run" subtitle={error instanceof Error ? error.message : "Run not found"} backTo={projectId ? `/admin/projects/${projectId}#runs` : "/admin/projects"} />
        <div className="mx-auto w-full max-w-[1120px] px-5 py-5 md:px-6">
          <EmptyState message="This Project run could not be loaded." />
        </div>
      </div>
    );
  }

  const receipt = run.receipt;
  const review = run.review ?? {};
  const handoffUrl = review.handoff_url || receipt?.handoff_url || undefined;
  const changedFiles = receipt?.changed_files ?? [];
  const tests = receipt?.tests ?? [];
  const screenshots = receipt?.screenshots ?? [];
  const devTargets = run.dev_targets?.length ? run.dev_targets : receipt?.dev_targets ?? [];
  const dependencyInstance = run.dependency_stack?.instance;
  const suggestedFeedback = run.review?.recovery?.suggested_feedback || run.continuation_feedback || "";
  const followUpFeedback = feedback ?? suggestedFeedback;
  const latestFollowUpId = createdFollowUp?.task.id || run.review?.recovery?.latest_continuation_id || run.latest_continuation?.task_id;
  const canContinue = Boolean(run.review?.actions?.can_continue || run.review?.recovery?.can_continue) && !latestFollowUpId;
  const recoveryIcon = canContinue || latestFollowUpId ? <MessageSquarePlus size={14} /> : run.review?.reviewed ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />;
  const recoveryMeta = canContinue ? "can continue" : latestFollowUpId ? "follow-up" : run.review?.reviewed ? "closed" : "blocked";
  const terminalReviewed = isTerminalReviewed(run);
  const prMerged = Boolean(run.review?.merged_at);
  const implementationSessionPath = run.task.channel_id && run.task.session_id ? `/channels/${run.task.channel_id}/session/${run.task.session_id}` : null;
  const runStatus = String(run.task.status || run.status || "").toLowerCase();
  const runActive = runStatus === "pending" || runStatus === "running";
  const submitFollowUp = () => {
    if (!canContinue || continueRun.isPending) return;
    continueRun.mutate(
      { taskId: run.task.id, feedback: followUpFeedback.trim() },
      {
        onSuccess: (created) => {
          setCreatedFollowUp(created);
          setFeedback(null);
        },
      },
    );
  };
  const recoverySection = (
    <Section title="Recovery" description="Start a follow-up implementation run when this run is blocked, failed, stale, or needs changes.">
      <div className="flex flex-col gap-2">
        <SettingsControlRow
          leading={recoveryIcon}
          title={recoveryTitle(run)}
          description={recoveryLine(run)}
          meta={<StatusBadge label={recoveryMeta} variant={canContinue || latestFollowUpId ? "info" : "neutral"} />}
          action={latestFollowUpId ? <RowLink to={`/admin/projects/${project.id}/runs/${latestFollowUpId}`}>{createdFollowUp ? "Open follow-up" : "Latest follow-up"}</RowLink> : undefined}
        />
        {canContinue ? (
          <div className="rounded-md bg-surface-raised/40 px-3 py-3">
            <label className="mb-2 block text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">
              Follow-up feedback
            </label>
            <textarea
              value={followUpFeedback}
              onChange={(event) => setFeedback(event.target.value)}
              rows={3}
              className="min-h-[84px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] text-text outline-none focus:border-accent"
              placeholder="Describe exactly what the follow-up agent should fix, verify, or explain..."
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[11px] text-text-dim">
                {createdFollowUp ? `Created follow-up ${createdFollowUp.task.id}` : "Uses the existing Project coding-run continuation path."}
              </span>
              <ActionButton
                label={continueRun.isPending ? "Starting" : "Start follow-up"}
                icon={<MessageSquarePlus size={13} />}
                size="small"
                disabled={continueRun.isPending}
                onPress={submitFollowUp}
              />
            </div>
          </div>
        ) : null}
      </div>
    </Section>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        chrome="flow"
        title={lifecycleHeadline(run)}
        subtitle={`${project.name} · ${formatRunTime(run.updated_at || run.created_at)} · ${reviewStatus(run).replaceAll("_", " ")}`}
        backTo={`/admin/projects/${project.id}#runs`}
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {(String(run.task?.status || run.status || "").toLowerCase() === "running" || (run.loop?.enabled && run.loop?.state && run.loop.state !== "stopped")) && (
              <RowLink to={`/admin/projects/${project.id}/runs/${run.task.id}/live`}>Live view</RowLink>
            )}
            <RowLink to={`/admin/projects/${project.id}#runs`}>Runs</RowLink>
            {implementationSessionPath && <RowLink to={implementationSessionPath}>Open session</RowLink>}
            {handoffUrl && <RowLink href={handoffUrl}>PR / handoff</RowLink>}
            {reviewAgentTaskId(run) && <RowLink to={`/admin/tasks/${reviewAgentTaskId(run)}`}>Review agent log</RowLink>}
            <RowLink to={`/admin/tasks/${run.task.id}`}>Task log</RowLink>
          </div>
        }
      />

      <div data-testid="project-run-detail" className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
          <Section title="Problem Statement" description="The source issue, requested work, and current close-out state for this run.">
            <div className="flex flex-col gap-3">
              <SettingsControlRow
                leading={<CheckCircle2 size={14} />}
                title="Next action"
                description={run.lifecycle?.blocker || lifecycleNextAction(run)}
                meta={<StatusBadge label={reviewStatus(run)} variant={statusTone(reviewStatus(run))} />}
              />
              <div className="rounded-md bg-surface-overlay/35 px-4 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={reviewStatus(run)} variant={statusTone(reviewStatus(run))} />
                  {prMerged && <StatusBadge label="merged" variant="success" />}
                  {terminalReviewed && <StatusBadge label="reviewed" variant="success" />}
                </div>
                <h1 className="mt-3 text-xl font-semibold leading-7 tracking-normal text-text">{problemTitle(run)}</h1>
                <p className="mt-3 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-text-muted">{problemSummary(run)}</p>
                <div className="mt-3 text-xs text-text-dim">{sourceLine(run)}</div>
              </div>
              {run.source_artifact?.path && (
                <div className="rounded-md bg-surface-overlay/25 px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">Source Artifact</div>
                  <div className="mt-1 text-sm font-semibold text-text">{run.source_artifact.path}{run.source_artifact.section ? ` · ${run.source_artifact.section}` : ""}</div>
                  {run.source_artifact.commit_sha && (
                    <div className="mt-1 text-xs text-text-dim">commit {String(run.source_artifact.commit_sha).slice(0, 8)}</div>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-overlay/25 px-3 py-2">
                <div className="line-clamp-2 min-w-0 text-xs leading-5 text-text-muted">
                  {terminalReviewed
                    ? `Closed on our side${run.review?.reviewed_at ? ` · ${formatRunTime(run.review.reviewed_at)}` : ""}${run.review?.review_summary ? ` · ${run.review.review_summary}` : ""}`
                    : prMerged
                      ? "PR is merged. Mark this run reviewed to close it on our side."
                    : lifecycleNextAction(run)}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {!terminalReviewed && run.review?.actions?.can_mark_reviewed && (
                    <ActionButton
                      label={markReviewed.isPending ? "Closing" : "Close on our side"}
                      icon={<CheckCircle2 size={13} />}
                      size="small"
                      disabled={markReviewed.isPending}
                      onPress={() => markReviewed.mutate(run.task.id)}
                    />
                  )}
                  <ActionButton
                    label="Back to runs"
                    icon={<ExternalLink size={13} />}
                    size="small"
                    variant="secondary"
                    onPress={() => navigate(`/admin/projects/${project.id}#runs`)}
                  />
                  {runActive && (
                    <ActionButton
                      label={cancelRun.isPending ? "Stopping" : "Stop run"}
                      icon={<AlertTriangle size={13} />}
                      size="small"
                      variant="danger"
                      disabled={cancelRun.isPending}
                      onPress={() => cancelRun.mutate(run.task.id)}
                    />
                  )}
                </div>
              </div>
            </div>
          </Section>

          <Section title="Agent Visibility" description="The concrete task records where implementation and review agents run.">
            <div className="grid gap-2 md:grid-cols-2">
              <SettingsControlRow
                leading={<TerminalSquare size={14} />}
                title="Implementation agent"
                description={[run.task.status, run.task.bot_id, run.task.session_id ? `session ${String(run.task.session_id).slice(0, 8)}` : null].filter(Boolean).join(" · ")}
                meta={<StatusBadge label={run.task.status || run.status} variant={statusTone(run.task.status || run.status)} />}
                action={implementationSessionPath ? <RowLink to={implementationSessionPath}>Open visible session</RowLink> : <RowLink to={`/admin/tasks/${run.task.id}`}>Open task log</RowLink>}
              />
              {reviewAgentTaskId(run) ? (
                <SettingsControlRow
                  leading={<GitMerge size={14} />}
                  title="Review agent"
                  description={[run.review?.review_session_id ? `session ${String(run.review.review_session_id).slice(0, 8)}` : null, run.review?.review_summary || run.review_next_action].filter(Boolean).join(" · ") || "Review task linked to this run"}
                  meta={<StatusBadge label={run.review_queue_state || "review task"} variant={statusTone(run.review_queue_state || "reviewing")} />}
                  action={<RowLink to={`/admin/tasks/${reviewAgentTaskId(run)}`}>Open review agent</RowLink>}
                />
              ) : (
                <SettingsControlRow
                  leading={<GitMerge size={14} />}
                  title="No review agent linked"
                  description="Ask an agent to review from the Project Runs page when you want another visible agent session to inspect or merge this work."
                  meta={<StatusBadge label="none" variant="neutral" />}
                  action={<RowLink to={`/admin/projects/${project.id}#runs`}>Open runs</RowLink>}
                />
              )}
            </div>
          </Section>

          <Section title="Run Summary" description="Current status, source branch, review state, and handoff links.">
            <div className="grid gap-2 md:grid-cols-2">
              <SettingsControlRow
                leading={<GitBranch size={14} />}
                title={run.branch || "No branch recorded"}
                description={`Base ${run.base_branch || "not recorded"}${run.repo?.path ? ` · ${run.repo.path}` : ""}`}
                meta={<StatusBadge label={reviewStatus(run)} variant={statusTone(reviewStatus(run))} />}
              />
              <SettingsControlRow
                leading={<GitMerge size={14} />}
                title={handoffUrl ? "Review handoff linked" : "No handoff linked"}
                description={prLine(run)}
                action={handoffUrl ? <RowLink href={handoffUrl}>Open</RowLink> : undefined}
              />
              <SettingsControlRow
                leading={<CheckCircle2 size={14} />}
                title={receipt?.summary || "No receipt summary recorded"}
                description={`Receipt ${receipt?.status || "missing"} · ${receipt ? formatRunTime(receipt.created_at) : "not published"}`}
                meta={<StatusBadge label={receipt?.status || "no receipt"} variant={statusTone(receipt?.status || "pending")} />}
              />
              <SettingsControlRow
                leading={<ServerCog size={14} />}
                title={dependencyInstance ? `Dependency stack ${dependencyInstance.status}` : "Dependency stack not prepared"}
                description={dependencyInstance ? `${dependencyInstance.source_path || dependencyInstance.id} · env ${Object.keys(dependencyInstance.env ?? {}).length}` : "No task dependency instance recorded"}
              />
              <SettingsControlRow
                leading={<TerminalSquare size={14} />}
                title={workSurfaceTitle(run)}
                description={workSurfaceLine(run)}
                meta={<StatusBadge label={run.work_surface?.isolation || "unknown"} variant={run.work_surface?.active === false ? "warning" : statusTone(run.work_surface?.status || "ready")} />}
              />
            </div>
          </Section>

          {recoverySection}

          {run.loop?.enabled && (
            <Section
              title="Bounded Loop"
              description="Automatic continuation state driven by explicit loop decisions in Project run receipts."
              action={
                <ActionButton
                  label={disableLoop.isPending ? "Stopping" : "Stop loop"}
                  icon={<Repeat2 size={13} />}
                  size="small"
                  variant="secondary"
                  disabled={disableLoop.isPending}
                  onPress={() => disableLoop.mutate(run.task.id)}
                />
              }
            >
              <div className="flex flex-col gap-2">
                <SettingsControlRow
                  leading={<Repeat2 size={14} />}
                  title={loopLine(run)}
                  description={run.loop.stop_condition || "No stop condition recorded."}
                  meta={<StatusBadge label={run.loop.state || "loop"} variant={run.loop.state === "continue" ? "info" : statusTone(run.loop.latest_decision || run.loop.state || "pending")} />}
                />
                {(run.loop.iterations ?? []).map((item, index) => (
                  <SettingsControlRow
                    key={`${item.task_id || index}`}
                    leading={<GitBranch size={14} />}
                    title={`Iteration ${(item.continuation_index ?? index) + 1}${item.decision ? ` · ${item.decision}` : ""}`}
                    description={[item.reason, item.remaining_work, item.updated_at ? formatRunTime(item.updated_at) : null].filter(Boolean).join(" · ") || item.status || "No receipt decision yet"}
                    meta={<StatusBadge label={item.status || item.task_status || "pending"} variant={statusTone(item.status || item.task_status || "pending")} />}
                    action={item.task_id && item.task_id !== run.task.id ? <RowLink to={`/admin/projects/${project.id}/runs/${item.task_id}`}>Open</RowLink> : undefined}
                  />
                ))}
              </div>
            </Section>
          )}

          <Section title="Review Decision" description="Reviewer outcome, merge metadata, blockers, and detailed review notes.">
            <div className="flex flex-col gap-2">
              <SettingsControlRow
                leading={review.blocker ? <AlertTriangle size={14} /> : <GitMerge size={14} />}
                title={review.review_summary || (review.reviewed ? "Run marked reviewed" : "No review summary recorded")}
                description={review.blocker ? `Blocker: ${review.blocker}` : `Reviewed ${review.reviewed_at ? formatRunTime(review.reviewed_at) : review.reviewed ? "yes" : "not yet"}${review.reviewed_by ? ` by ${review.reviewed_by}` : ""}`}
                meta={<StatusBadge label={reviewStatus(run)} variant={statusTone(reviewStatus(run))} />}
              />
              {(review.merge_method || review.merged_at || review.merge_commit_sha) && (
                <SettingsControlRow
                  leading={<GitMerge size={14} />}
                  title={`Merge ${review.merge_method || "recorded"}`}
                  description={[review.merged_at ? formatRunTime(review.merged_at) : null, review.merge_commit_sha ? `commit ${String(review.merge_commit_sha).slice(0, 12)}` : null].filter(Boolean).join(" · ")}
                />
              )}
              {review.review_details && Object.keys(review.review_details).length > 0 ? (
                <JsonBlock value={review.review_details} />
              ) : (
                <EmptyState message="No structured review details were recorded." />
              )}
            </div>
          </Section>

          <div className="grid gap-7 lg:grid-cols-2">
            <EvidenceList title="Changed Files" icon={<FileText size={14} />} values={changedFiles} empty="No changed files were reported." />
            <EvidenceList title="Tests" icon={<ListChecks size={14} />} values={tests} empty="No test commands were reported." />
            <EvidenceList title="Screenshots" icon={<Monitor size={14} />} values={screenshots} empty="No screenshots were reported." />
            <EvidenceList title="Dev Targets" icon={<TerminalSquare size={14} />} values={devTargets} empty="No dev target URLs or ports were reported." />
          </div>

          <Section title="Activity Timeline" description="Recent durable progress receipts and task activity for this run.">
            <div className="flex flex-col gap-2">
              {(run.activity ?? []).length === 0 ? (
                <EmptyState message="No recent activity was recorded." />
              ) : (
                (run.activity ?? []).map((item, index) => (
                  <SettingsControlRow
                    key={`${item.id || item.created_at || index}`}
                    leading={<ExternalLink size={14} />}
                    title={String(item.summary || item.title || item.tool_name || item.kind || `Activity ${index + 1}`)}
                    description={[item.created_at ? formatRunTime(String(item.created_at)) : null, item.source?.action_type, item.status].filter(Boolean).join(" · ")}
                    meta={item.status ? <StatusBadge label={String(item.status)} variant={statusTone(String(item.status))} /> : undefined}
                  />
                ))
              )}
            </div>
          </Section>

          <Section title="Receipt Metadata" description="Raw structured evidence published by the implementation agent.">
            <JsonBlock value={{
              receipt_metadata: receipt?.metadata ?? {},
              loop: run.loop ?? {},
              work_surface: run.work_surface ?? {},
              dependency_stack: run.dependency_stack ?? {},
              readiness: run.readiness ?? {},
              task: run.task,
            }} />
          </Section>
        </div>
      </div>
    </div>
  );
}
