import { FolderOpen } from "lucide-react";
import {
  useClearSessionProjectInstance,
  useCreateSessionProjectInstance,
  useSessionProjectInstance,
} from "@/src/api/hooks/useChannelSessions";

interface SessionWorkSurfaceControlProps {
  sessionId?: string | null;
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
  presentation = "composer",
}: SessionWorkSurfaceControlProps) {
  const { data, isLoading, error } = useSessionProjectInstance(sessionId);
  const createInstance = useCreateSessionProjectInstance(sessionId);
  const clearInstance = useClearSessionProjectInstance(sessionId);

  if (!sessionId || isLoading || error || !data?.project_id || !data.root_path) return null;

  const bound = Boolean(data.project_instance_id);
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
        {href && (
          <a
            href={href}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
          >
            <FolderOpen size={12} />
            Open files
          </a>
        )}
        {bound ? (
          <button
            type="button"
            disabled={clearInstance.isPending}
            onClick={() => clearInstance.mutate()}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-50"
          >
            Return to shared Project
          </button>
        ) : (
          <button
            type="button"
            disabled={createInstance.isPending}
            onClick={() => createInstance.mutate()}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-50"
          >
            Start isolated Project session
          </button>
        )}
        {(createInstance.error || clearInstance.error) && (
          <div className="px-2 py-1 text-[11px] text-danger">
            {(createInstance.error || clearInstance.error) instanceof Error
              ? (createInstance.error || clearInstance.error)?.message
              : "Work surface update failed."}
          </div>
        )}
      </div>
    );
  }

  return null;
}
