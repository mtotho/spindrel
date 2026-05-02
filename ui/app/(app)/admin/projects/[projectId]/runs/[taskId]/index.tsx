import { AlertTriangle, CheckCircle2, ExternalLink, FileText, GitBranch, GitMerge, ListChecks, Monitor, ServerCog, TerminalSquare } from "lucide-react";
import type React from "react";
import { useParams } from "react-router-dom";

import { useProject, useProjectCodingRun } from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Section } from "@/src/components/shared/FormControls";
import { EmptyState, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
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
  return run.review?.status || run.status;
}

function runTitle(run: ProjectCodingRun) {
  return run.request || run.task.title || "Project coding run";
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

export default function ProjectRunDetail() {
  const { projectId, taskId } = useParams<{ projectId: string; taskId: string }>();
  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data: run, isLoading: runLoading, error } = useProjectCodingRun(projectId, taskId);

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

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        chrome="flow"
        title={runTitle(run)}
        subtitle={`${project.name} · ${formatRunTime(run.updated_at || run.created_at)}`}
        backTo={`/admin/projects/${project.id}#runs`}
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {handoffUrl && <RowLink href={handoffUrl}>Handoff</RowLink>}
            <RowLink to={`/admin/tasks/${run.task.id}`}>Task</RowLink>
          </div>
        }
      />

      <div data-testid="project-run-detail" className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
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
