import { RefreshCcw } from "lucide-react";

import { useProjectGitStatus } from "@/src/api/hooks/useProjects";
import { ActionButton, EmptyState, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

export function ProjectGitPanel({ projectId }: { projectId: string }) {
  const { data, isLoading, isFetching, refetch } = useProjectGitStatus(projectId, { includePatch: true });

  if (isLoading) {
    return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  }

  const repos = data?.repos ?? [];
  return (
    <div data-testid="project-git-panel" className="mx-auto flex w-full max-w-[1400px] flex-col gap-3 px-4 py-4 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-raised/35 px-3 py-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text">Git status</div>
          <div className="text-[12px] text-text-muted">
            {repos.length} repo{repos.length === 1 ? "" : "s"} · {data?.dirty_count ?? 0} dirty
          </div>
        </div>
        <ActionButton label={isFetching ? "Refreshing" : "Refresh"} icon={<RefreshCcw size={13} />} size="small" variant="secondary" disabled={isFetching} onPress={() => refetch()} />
      </div>

      {repos.length === 0 ? (
        <EmptyState message="No Git repositories were detected under this Project." />
      ) : (
        <div className="grid gap-3">
          {repos.map((repo) => (
            <section key={repo.path} className="rounded-md border border-surface-border bg-surface-raised/25">
              <div className="flex flex-wrap items-start justify-between gap-2 border-b border-surface-border/60 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate font-mono text-[12px] font-semibold text-text">{repo.display_path || repo.path}</div>
                  <div className="truncate text-[11px] text-text-muted">
                    {repo.branch || "detached"}{repo.head ? ` · ${repo.head}` : ""}
                  </div>
                </div>
                <StatusBadge label={repo.error ? "error" : repo.dirty ? "dirty" : "clean"} variant={repo.error ? "danger" : repo.dirty ? "warning" : "success"} />
              </div>
              <div className="grid gap-2 p-3 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
                <div className="min-h-[96px] rounded bg-surface/55 p-2 font-mono text-[11px] text-text-muted">
                  {repo.error ? (
                    <div className="text-danger-muted">{repo.error}</div>
                  ) : repo.status_lines.length ? (
                    repo.status_lines.map((line) => <div key={line}>{line}</div>)
                  ) : (
                    <div>working tree clean</div>
                  )}
                </div>
                <pre className="max-h-[520px] overflow-auto rounded bg-[#080b10] p-3 text-[11px] leading-5 text-zinc-300">
                  {repo.patch || repo.diff_stat || "No diff."}
                </pre>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
