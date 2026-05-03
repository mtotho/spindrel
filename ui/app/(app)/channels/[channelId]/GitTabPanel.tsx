import { useProjectGitStatus, useSessionGitStatus } from "@/src/api/hooks/useProjects";
import { EmptyState, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import type { ProjectSummary } from "@/src/types/api";

export function GitTabPanel({
  project,
  activeSessionId,
}: {
  project?: ProjectSummary | null;
  activeSessionId?: string | null;
}) {
  const sessionQuery = useSessionGitStatus(activeSessionId, { includePatch: true });
  const projectQuery = useProjectGitStatus(!activeSessionId ? project?.id : undefined, { includePatch: true });
  const query = activeSessionId ? sessionQuery : projectQuery;
  const repos = query.data?.repos ?? [];

  if (!activeSessionId && !project?.id) {
    return <EmptyState message="This channel is not attached to a Project Git surface." />;
  }
  if (query.isLoading) {
    return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-auto px-2 py-2 scroll-subtle">
      <div className="px-1 text-[11px] font-semibold text-text-muted">
        {activeSessionId ? "Session Git" : "Project Git"} · {repos.length} repo{repos.length === 1 ? "" : "s"} · {query.data?.dirty_count ?? 0} dirty
      </div>
      {repos.length === 0 ? (
        <EmptyState message="No Git repositories were detected." />
      ) : repos.map((repo) => (
        <section key={repo.path} className="rounded-md bg-surface-raised/45">
          <div className="flex items-start justify-between gap-2 border-b border-surface-border/60 px-2 py-2">
            <div className="min-w-0">
              <div className="truncate font-mono text-[11px] font-semibold text-text">{repo.display_path || repo.path}</div>
              <div className="truncate text-[10px] text-text-dim">{repo.branch || "detached"}</div>
            </div>
            <StatusBadge label={repo.error ? "error" : repo.dirty ? "dirty" : "clean"} variant={repo.error ? "danger" : repo.dirty ? "warning" : "success"} />
          </div>
          <div className="grid gap-2 p-2">
            <pre className="max-h-32 overflow-auto rounded bg-surface/70 p-2 font-mono text-[10px] leading-4 text-text-muted">
              {repo.error || repo.status_lines.join("\n") || "working tree clean"}
            </pre>
            <pre className="max-h-72 overflow-auto rounded bg-[#080b10] p-2 font-mono text-[10px] leading-4 text-zinc-300">
              {repo.patch || repo.diff_stat || "No diff."}
            </pre>
          </div>
        </section>
      ))}
    </div>
  );
}
