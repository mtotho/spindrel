import { ExternalLink, Eye } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useProject, useProjectCodingRun } from "@/src/api/hooks/useProjects";
import { SessionChatView } from "@/src/components/chat/SessionChatView";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Section } from "@/src/components/shared/FormControls";
import { ActionButton, EmptyState, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import type { ProjectCodingRun } from "@/src/types/api";
import { formatRunTime, RowLink, statusTone } from "../../ProjectRunControls";

const TERMINAL_STATUSES = new Set(["complete", "completed", "needs_review", "failed", "blocked", "cancelled", "canceled"]);

function isRunActive(run: ProjectCodingRun) {
  const status = String(run.task?.status || run.status || "").toLowerCase();
  if (TERMINAL_STATUSES.has(status)) return false;
  return status === "running" || status === "pending" || status === "active" || Boolean(run.loop?.enabled && run.loop?.state && run.loop.state !== "stopped");
}

function devTargetUrl(run: ProjectCodingRun): string | null {
  const targets = run.dev_targets || [];
  for (const target of targets) {
    if (target && typeof target === "object") {
      const url = (target as Record<string, any>).url;
      if (typeof url === "string" && url.length > 0) return url;
    }
  }
  return null;
}

function ProgressDots({ current, total }: { current: number; total: number }) {
  const safeTotal = Math.max(1, Math.min(total, 32));
  const safeCurrent = Math.max(0, Math.min(current, safeTotal));
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: safeTotal }).map((_, idx) => {
        const filled = idx < safeCurrent;
        const isCurrent = idx === safeCurrent - 1;
        return (
          <span
            key={idx}
            className={`h-1.5 rounded-full transition-colors ${filled ? (isCurrent ? "w-3 bg-accent" : "w-1.5 bg-accent/70") : "w-1.5 bg-border-subtle"}`}
          />
        );
      })}
    </div>
  );
}

function CollapsiblePrompt({ text, defaultOpen }: { text: string; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (!text) return <p className="text-sm text-text-dim">No launch prompt was recorded for this run.</p>;
  const isLong = text.length > 320;
  return (
    <div className="flex flex-col gap-2">
      <pre
        className={`whitespace-pre-wrap rounded-md border border-border-subtle bg-input/60 p-3 text-[12.5px] leading-relaxed text-text ${open ? "max-h-[420px] overflow-auto" : "max-h-[88px] overflow-hidden"}`}
      >
        {text}
      </pre>
      {isLong && (
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="self-start text-[11px] font-semibold uppercase tracking-[0.08em] text-accent hover:underline"
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

export default function ProjectRunLive() {
  const { projectId, taskId } = useParams<{ projectId: string; taskId: string }>();
  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data: run, isLoading: runLoading, error } = useProjectCodingRun(projectId, taskId);

  const status = String(run?.task?.status || run?.status || "").toLowerCase();
  const active = run ? isRunActive(run) : false;
  const loop = run?.loop;
  const iteration = loop?.iteration ?? 1;
  const maxIterations = loop?.max_iterations ?? 1;
  const promptText = useMemo(() => run?.request || run?.task?.title || "", [run]);
  const channelId = run?.task?.channel_id || null;
  const sessionId = run?.task?.session_id || null;
  const botId = run?.task?.bot_id || undefined;
  const handoffUrl = run?.review?.handoff_url || run?.receipt?.handoff_url || null;
  const devUrl = run ? devTargetUrl(run) : null;
  const branchName = (run?.review as any)?.branch || (run?.receipt as any)?.branch || null;

  if (projectLoading || runLoading) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }
  if (error || !run || !project) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface p-6">
        <EmptyState message="Run not found — this Project coding run could not be loaded." />
      </div>
    );
  }

  const ribbonLabel = `iteration ${iteration}/${maxIterations}${loop?.state ? ` · ${loop.state}` : ""}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        chrome="flow"
        title={run.task?.title || run.request || "Project coding run"}
        subtitle={`${project.name} · live · ${formatRunTime(run.updated_at || run.created_at)}`}
        backTo={`/admin/projects/${project.id}#runs`}
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <StatusBadge label={status || "unknown"} variant={statusTone(status)} />
            <RowLink to={`/admin/projects/${project.id}/runs/${run.task.id}`}>Full detail</RowLink>
            {sessionId && <RowLink to={`/admin/sessions/${sessionId}`}>Open session</RowLink>}
            {channelId && <RowLink to={`/channels/${channelId}`}>Open channel</RowLink>}
          </div>
        }
      />

      <div data-testid="project-run-live" className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-5 px-5 py-5 md:px-6">
          {loop?.enabled && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-surface-overlay/35 px-4 py-3">
              <div className="flex items-center gap-3">
                <Eye size={14} className="text-accent" />
                <span className="text-sm font-semibold text-text">{ribbonLabel}</span>
                {loop?.latest_decision && (
                  <span className="text-xs text-text-dim">last decision · {loop.latest_decision}</span>
                )}
              </div>
              <ProgressDots current={iteration} total={maxIterations} />
            </div>
          )}

          <Section title="Original prompt" description="The launch request that started this run.">
            <CollapsiblePrompt text={promptText} defaultOpen={iteration <= 1} />
          </Section>

          {!active && (
            <div className="rounded-md border border-border-subtle bg-surface-overlay/35 px-4 py-3 text-sm text-text-muted">
              Run finished · <span className="font-semibold text-text">{status || "unknown"}</span> ·{" "}
              <Link to={`/admin/projects/${project.id}/runs/${run.task.id}`} className="text-accent hover:underline">
                Open Full detail for review
              </Link>
            </div>
          )}

          <Section title="Live transcript" description={sessionId ? `Streaming session ${String(sessionId).slice(0, 8)}` : "No session id linked yet"}>
            {sessionId ? (
              <div className="flex h-[60vh] min-h-[420px] flex-col overflow-hidden rounded-md border border-border-subtle bg-surface">
                <SessionChatView
                  key={sessionId}
                  sessionId={sessionId}
                  parentChannelId={channelId || undefined}
                  botId={botId}
                />
              </div>
            ) : (
              <EmptyState message="No active session — the current iteration has not produced a session yet. The transcript will appear here as soon as the agent starts." />
            )}
          </Section>

          <div className="flex flex-wrap items-center gap-2 rounded-md bg-surface-overlay/25 px-3 py-2 text-xs text-text-muted">
            {branchName && <span>branch <span className="font-mono text-text">{branchName}</span></span>}
            {handoffUrl && <RowLink href={handoffUrl}>PR / handoff</RowLink>}
            {devUrl && (
              <a href={devUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                <ExternalLink size={11} /> dev target
              </a>
            )}
            {run.work_surface?.status && <StatusBadge label={`surface ${run.work_surface.status}`} variant="neutral" />}
            {run.dependency_stack?.instance?.status && <StatusBadge label={`stack ${run.dependency_stack.instance.status}`} variant="neutral" />}
            {!branchName && !handoffUrl && !devUrl && !run.work_surface?.status && (
              <ActionButton
                label="Open Full detail"
                icon={<ExternalLink size={12} />}
                size="small"
                variant="secondary"
                onPress={() => {
                  window.location.href = `/admin/projects/${project.id}/runs/${run.task.id}`;
                }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
