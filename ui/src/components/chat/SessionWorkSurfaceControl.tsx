import { ExternalLink, FolderOpen, Plus, X } from "lucide-react";
import {
  useClearSessionProjectInstance,
  useCreateSessionProjectInstance,
  useSessionProjectInstance,
} from "@/src/api/hooks/useChannelSessions";

interface SessionWorkSurfaceControlProps {
  sessionId?: string | null;
  disabled?: boolean;
  presentation?: "composer" | "menu";
}

function shortPath(path?: string | null) {
  if (!path) return "";
  const normalized = path.replace(/^\/+/, "");
  if (normalized.length <= 38) return normalized;
  const parts = normalized.split("/");
  if (parts.length <= 2) return `.../${normalized.slice(-32)}`;
  return `.../${parts.slice(-2).join("/")}`;
}

function filesHref(workspaceId?: string | null, rootPath?: string | null) {
  if (!workspaceId || !rootPath) return null;
  return `/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(`/${rootPath.replace(/^\/+/, "")}`)}`;
}

export function SessionWorkSurfaceControl({
  sessionId,
  disabled = false,
  presentation = "composer",
}: SessionWorkSurfaceControlProps) {
  const { data, isLoading, error } = useSessionProjectInstance(sessionId);
  const createInstance = useCreateSessionProjectInstance(sessionId);
  const clearInstance = useClearSessionProjectInstance(sessionId);

  if (!sessionId || isLoading || error || !data?.project_id || !data.root_path) return null;

  const bound = Boolean(data.project_instance_id);
  const busy = createInstance.isPending || clearInstance.isPending;
  const mutatingDisabled = disabled || busy;
  const label = bound ? "Fresh" : "Project";
  const href = filesHref(data.workspace_id, data.root_path);
  const title = `${label} workspace: /${data.root_path}`;

  if (presentation === "menu") {
    return (
      <div className="py-1" data-testid="session-work-surface-menu">
        <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Work surface</div>
        <div className="px-2 pb-1 text-[11px] text-text-dim">
          <span className="text-text-muted">{label}</span>{" "}
          <span className="font-mono">{shortPath(data.root_path)}</span>
        </div>
        {!bound ? (
          <button
            type="button"
            disabled={mutatingDisabled}
            onClick={() => createInstance.mutate()}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-45"
          >
            <Plus size={12} />
            Fresh copy
          </button>
        ) : (
          <>
            {href && (
              <a
                href={href}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
              >
                <FolderOpen size={12} />
                Open files
              </a>
            )}
            <button
              type="button"
              disabled={mutatingDisabled}
              onClick={() => clearInstance.mutate()}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-45"
            >
              <X size={12} />
              Use shared Project
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <div
      data-testid="session-work-surface-control"
      className="flex min-w-0 shrink items-center gap-1.5 text-[10px] text-text-dim"
      title={title}
    >
      <span className="shrink-0 uppercase tracking-[0.08em] text-text-dim/80">{label}</span>
      <span className="min-w-0 max-w-[15rem] truncate font-mono text-text-muted">{shortPath(data.root_path)}</span>
      {!bound ? (
        <button
          type="button"
          disabled={mutatingDisabled}
          onClick={() => createInstance.mutate()}
          className="shrink-0 rounded px-1 py-0.5 text-accent hover:bg-accent/[0.08] disabled:cursor-default disabled:opacity-45 disabled:hover:bg-transparent"
        >
          Fresh copy
        </button>
      ) : (
        <>
          {href && (
            <a
              href={href}
              className="shrink-0 rounded p-0.5 text-text-dim hover:bg-surface-overlay hover:text-text"
              aria-label="Open fresh workspace files"
              title="Open files"
            >
              <ExternalLink size={12} />
            </a>
          )}
          <button
            type="button"
            disabled={mutatingDisabled}
            onClick={() => clearInstance.mutate()}
            className="shrink-0 rounded p-0.5 text-text-dim hover:bg-surface-overlay hover:text-text disabled:cursor-default disabled:opacity-45 disabled:hover:bg-transparent disabled:hover:text-text-dim"
            aria-label="Use shared Project workspace"
            title="Use shared Project"
          >
            <X size={12} />
          </button>
        </>
      )}
    </div>
  );
}
