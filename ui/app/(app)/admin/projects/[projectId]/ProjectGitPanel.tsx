import { FileText, GitBranch, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useProjectGitStatus } from "@/src/api/hooks/useProjects";
import { ActionButton, EmptyState, StatusBadge } from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { DiffRenderer } from "@/src/components/chat/renderers/DiffRenderer";
import { projectGitRepoDirty, projectGitRepoError, projectGitStatusLines } from "@/src/lib/projectGitStatus";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ProjectGitRepoStatus, ProjectGitStatus } from "@/src/types/api";

type GitFileChange = {
  path: string;
  oldPath?: string;
  status: string;
  statusLabel: string;
  patch: string;
  additions: number;
  deletions: number;
};

const STATUS_LABELS: Record<string, string> = {
  A: "added",
  C: "copied",
  D: "deleted",
  M: "modified",
  R: "renamed",
  T: "type changed",
  U: "unmerged",
  "?": "untracked",
};

function normalizeDiffPath(value: string) {
  if (value === "/dev/null") return "";
  return value.replace(/^"?[ab]\//, "").replace(/"$/, "");
}

function filePathFromStatusLine(line: string) {
  const raw = line.slice(3).trim();
  if (raw.includes(" -> ")) return raw.split(" -> ").pop()?.trim() || raw;
  return raw;
}

function statusLabel(status: string) {
  if (status === "??") return "untracked";
  const chars = Array.from(new Set(status.replace(/\s/g, "").split("")));
  return chars.map((char) => STATUS_LABELS[char] || char).join(", ") || "changed";
}

function parsePatchFiles(patch: string): Map<string, Pick<GitFileChange, "path" | "oldPath" | "patch" | "additions" | "deletions">> {
  const files = new Map<string, Pick<GitFileChange, "path" | "oldPath" | "patch" | "additions" | "deletions">>();
  if (!patch.trim()) return files;
  const chunks = patch.split(/^diff --git /m).filter((chunk) => chunk.trim());
  for (const chunk of chunks) {
    const body = `diff --git ${chunk}`;
    const firstLine = body.split("\n", 1)[0] || "";
    const match = /^diff --git "?a\/(.+?)"? "?b\/(.+?)"?$/.exec(firstLine);
    let oldPath = match?.[1] || "";
    let path = match?.[2] || oldPath;
    for (const line of body.split("\n")) {
      if (line.startsWith("--- ")) oldPath = normalizeDiffPath(line.slice(4).trim()) || oldPath;
      if (line.startsWith("+++ ")) path = normalizeDiffPath(line.slice(4).trim()) || path;
    }
    if (!path) path = oldPath || "unknown";
    const additions = body.split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++")).length;
    const deletions = body.split("\n").filter((line) => line.startsWith("-") && !line.startsWith("---")).length;
    files.set(path, { path, oldPath: oldPath && oldPath !== path ? oldPath : undefined, patch: body, additions, deletions });
  }
  return files;
}

function repoFileChanges(repo: ProjectGitRepoStatus): GitFileChange[] {
  const patchFiles = parsePatchFiles(repo.patch || "");
  const byPath = new Map<string, GitFileChange>();
  for (const line of projectGitStatusLines(repo)) {
    const path = filePathFromStatusLine(line);
    const status = line.slice(0, 2);
    const patch = patchFiles.get(path);
    byPath.set(path, {
      path,
      oldPath: patch?.oldPath,
      status,
      statusLabel: statusLabel(status),
      patch: patch?.patch || "",
      additions: patch?.additions ?? 0,
      deletions: patch?.deletions ?? 0,
    });
  }
  for (const patch of patchFiles.values()) {
    if (byPath.has(patch.path)) continue;
    byPath.set(patch.path, {
      path: patch.path,
      oldPath: patch.oldPath,
      status: " M",
      statusLabel: "modified",
      patch: patch.patch,
      additions: patch.additions,
      deletions: patch.deletions,
    });
  }
  return Array.from(byPath.values()).sort((a, b) => a.path.localeCompare(b.path));
}

function statusTone(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "??") return "info";
  if (status.includes("D")) return "danger";
  if (status.includes("A") || status.includes("R")) return "success";
  if (status.trim()) return "warning";
  return "neutral";
}

export function ProjectGitPanel({ projectId }: { projectId: string }) {
  const { data, isLoading, isFetching, refetch } = useProjectGitStatus(projectId, { includePatch: true });

  return (
    <ProjectGitStatusView
      data={data}
      isLoading={isLoading}
      isFetching={isFetching}
      onRefresh={() => refetch()}
      className="mx-auto max-w-[1400px] px-4 py-4 sm:px-6 lg:px-8"
      emptyMessage="No Git repositories were detected under this Project."
    />
  );
}

export function ProjectGitStatusView({
  data,
  isLoading,
  isFetching,
  onRefresh,
  className = "",
  title = "Git status",
  emptyMessage = "No Git repositories were detected.",
}: {
  data?: ProjectGitStatus;
  isLoading: boolean;
  isFetching: boolean;
  onRefresh: () => void;
  className?: string;
  title?: string;
  emptyMessage?: string;
}) {
  if (isLoading) {
    return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  }

  const repos = data?.repos ?? [];
  return (
    <div data-testid="project-git-panel" className={`flex w-full flex-col gap-3 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-surface-raised/35 px-3 py-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text">{title}</div>
          <div className="text-[12px] text-text-muted">
            {repos.length} repo{repos.length === 1 ? "" : "s"} · {data?.dirty_count ?? 0} dirty
          </div>
        </div>
        <ActionButton label={isFetching ? "Refreshing" : "Refresh"} icon={<RefreshCcw size={13} />} size="small" variant="secondary" disabled={isFetching} onPress={onRefresh} />
      </div>

      {repos.length === 0 ? (
        <EmptyState message={emptyMessage} />
      ) : (
        <div className="grid gap-3">
          {repos.map((repo) => <ProjectGitRepoCard key={repo.path} repo={repo} />)}
        </div>
      )}
    </div>
  );
}

function ProjectGitRepoCard({ repo }: { repo: ProjectGitRepoStatus }) {
  const t = useThemeTokens();
  const statusLines = projectGitStatusLines(repo);
  const error = projectGitRepoError(repo);
  const dirty = projectGitRepoDirty(repo);
  const fileChanges = useMemo(() => repoFileChanges(repo), [repo]);
  const [selectedPath, setSelectedPath] = useState("");
  const selectedFile = fileChanges.find((file) => file.path === selectedPath) || fileChanges[0] || null;

  useEffect(() => {
    if (!selectedPath && fileChanges[0]) {
      setSelectedPath(fileChanges[0].path);
    } else if (selectedPath && !fileChanges.some((file) => file.path === selectedPath)) {
      setSelectedPath(fileChanges[0]?.path || "");
    }
  }, [fileChanges, selectedPath]);

  return (
    <section className="rounded-md border border-surface-border bg-surface-raised/25">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-surface-border/60 px-3 py-2">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <GitBranch size={14} className="shrink-0 text-text-dim" />
            <div className="truncate font-mono text-[12px] font-semibold text-text">{repo.display_path || repo.path}</div>
          </div>
          <div className="mt-1 truncate text-[11px] text-text-muted">
            {repo.branch || "detached"}{repo.head ? ` · ${repo.head}` : ""} · {fileChanges.length} changed file{fileChanges.length === 1 ? "" : "s"}
          </div>
        </div>
        <StatusBadge label={error ? "error" : dirty ? "dirty" : "clean"} variant={error ? "danger" : dirty ? "warning" : "success"} />
      </div>
      <div className="grid gap-2 p-3 lg:grid-cols-[minmax(260px,360px)_minmax(0,1fr)]">
        <div className="min-h-[220px] rounded-md bg-surface/55 p-2">
          {error ? (
            <div className="text-danger-muted">{error}</div>
          ) : fileChanges.length ? (
            <div className="flex max-h-[520px] flex-col gap-1 overflow-auto pr-1">
              {fileChanges.map((file) => (
                <button
                  type="button"
                  key={`${file.status}:${file.path}`}
                  onClick={() => setSelectedPath(file.path)}
                  className={[
                    "flex min-w-0 items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
                    selectedFile?.path === file.path ? "bg-accent/[0.10]" : "hover:bg-surface-overlay/45",
                  ].join(" ")}
                >
                  <FileText size={13} className="mt-0.5 shrink-0 text-text-dim" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[11px] font-semibold text-text">{file.path}</span>
                    {file.oldPath && <span className="block truncate text-[10px] text-text-dim">from {file.oldPath}</span>}
                    <span className="mt-1 flex items-center gap-1.5">
                      <StatusBadge label={file.statusLabel} variant={statusTone(file.status)} />
                      {file.patch ? (
                        <span className="font-mono text-[10px] text-text-dim">
                          <span className="text-success">+{file.additions}</span>{" "}
                          <span className="text-danger-muted">-{file.deletions}</span>
                        </span>
                      ) : (
                        <span className="text-[10px] text-text-dim">no patch</span>
                      )}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="p-2 text-[12px] text-text-muted">working tree clean</div>
          )}
        </div>
        <div className="min-h-[220px] min-w-0 rounded-md bg-surface/55 p-2">
          {selectedFile?.patch ? (
            <div className="min-w-0">
              <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2 px-1">
                <div className="min-w-0 flex-1 truncate font-mono text-[12px] font-semibold text-text">{selectedFile.path}</div>
                <span className="font-mono text-[11px] text-text-dim">
                  <span className="text-success">+{selectedFile.additions}</span>{" "}
                  <span className="text-danger-muted">-{selectedFile.deletions}</span>
                </span>
              </div>
              <DiffRenderer body={selectedFile.patch} t={t} />
            </div>
          ) : selectedFile ? (
            <div className="flex h-full min-h-[180px] flex-col items-center justify-center rounded-md border border-surface-border/45 bg-surface-raised/25 px-4 text-center">
              <div className="font-mono text-[12px] font-semibold text-text">{selectedFile.path}</div>
              <div className="mt-1 text-[12px] text-text-muted">
                {selectedFile.status === "??" ? "Untracked file content is not included in the Git patch preview." : "No line diff is available for this file."}
              </div>
            </div>
          ) : (
            <div className="flex h-full min-h-[180px] items-center justify-center text-[12px] text-text-muted">No diff.</div>
          )}
        </div>
      </div>
    </section>
  );
}
