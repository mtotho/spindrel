import { Link } from "react-router-dom";
import { FolderKanban, Plus } from "lucide-react";
import { useState } from "react";

import { useCreateProject, useProjects } from "@/src/api/hooks/useProjects";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";

export default function ProjectsIndex() {
  const { data: projects, isLoading } = useProjects();
  const { data: workspaces } = useWorkspaces();
  const createProject = useCreateProject();
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("common/projects");
  const defaultWorkspaceId = workspaces?.[0]?.id;

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedRoot = rootPath.trim();
    if (!trimmedName || !trimmedRoot || !defaultWorkspaceId) return;
    createProject.mutate({
      workspace_id: defaultWorkspaceId,
      name: trimmedName,
      root_path: trimmedRoot,
    }, {
      onSuccess: () => {
        setName("");
        setRootPath("common/projects");
      },
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader variant="list" title="Projects" subtitle="Shared working roots for channels, bots, files, and terminals" />
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto p-5">
        <div data-testid="project-workspace-create-form" className="grid gap-3 rounded-md border border-surface-border bg-surface-raised p-4 md:grid-cols-[1fr_1fr_auto]">
          <input
            className="h-10 rounded-md border border-surface-border bg-surface px-3 text-sm text-text outline-none"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Project name"
          />
          <input
            className="h-10 rounded-md border border-surface-border bg-surface px-3 text-sm text-text outline-none"
            value={rootPath}
            onChange={(event) => setRootPath(event.target.value)}
            placeholder="common/projects"
          />
          <button
            type="button"
            onClick={submit}
            disabled={!name.trim() || !rootPath.trim() || !defaultWorkspaceId || createProject.isPending}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-accent/40 bg-accent/15 px-3 text-sm font-semibold text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={15} />
            Create
          </button>
        </div>

        {isLoading ? (
          <div className="flex flex-1 items-center justify-center"><Spinner /></div>
        ) : (
          <div data-testid="project-workspace-list" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(projects ?? []).map((project) => (
              <Link
                key={project.id}
                data-testid="project-workspace-row"
                to={`/admin/projects/${project.id}`}
                className="rounded-md border border-surface-border bg-surface-raised p-4 text-text no-underline transition-colors hover:border-accent/50 hover:bg-surface-overlay/50"
              >
                <div className="flex items-center gap-3">
                  <FolderKanban size={18} className="text-accent" />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{project.name}</div>
                    <div className="truncate font-mono text-xs text-text-muted">/{project.root_path}</div>
                  </div>
                </div>
                <div className="mt-3 text-xs text-text-dim">{project.attached_channel_count ?? 0} attached channels</div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
