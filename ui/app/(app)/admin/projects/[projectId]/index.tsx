import { Link, useParams } from "react-router-dom";
import { ExternalLink, Save, Terminal } from "lucide-react";
import { useEffect, useState } from "react";

import { useProject, useProjectChannels, useUpdateProject } from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading } = useProject(projectId);
  const { data: channels } = useProjectChannels(projectId);
  const updateProject = useUpdateProject(projectId);
  const [prompt, setPrompt] = useState("");
  const [promptFilePath, setPromptFilePath] = useState("");

  useEffect(() => {
    setPrompt(project?.prompt ?? "");
    setPromptFilePath(project?.prompt_file_path ?? "");
  }, [project?.prompt, project?.prompt_file_path]);

  if (isLoading || !project) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }

  const root = project.root_path.replace(/^\/+|\/+$/g, "");
  const terminalHref = `/admin/terminal?cwd=${encodeURIComponent(`workspace://${project.workspace_id}/${root}`)}`;
  const filesHref = `/admin/workspaces/${project.workspace_id}/files?path=${encodeURIComponent(`/${root}`)}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        title={project.name}
        subtitle={`/${project.root_path}`}
        backTo="/admin/projects"
        right={
          <div className="flex items-center gap-2">
            <Link className="inline-flex h-9 items-center gap-2 rounded-md border border-surface-border px-3 text-sm text-text no-underline hover:bg-surface-overlay" to={filesHref}>
              <ExternalLink size={14} />
              Files
            </Link>
            <Link className="inline-flex h-9 items-center gap-2 rounded-md border border-surface-border px-3 text-sm text-text no-underline hover:bg-surface-overlay" to={terminalHref}>
              <Terminal size={14} />
              Terminal
            </Link>
          </div>
        }
      />
      <div className="grid min-h-0 flex-1 gap-5 overflow-auto p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="flex min-h-0 flex-col gap-3">
          <div data-testid="project-workspace-instructions" className="rounded-md border border-surface-border bg-surface-raised p-4">
            <div className="mb-3 text-sm font-semibold text-text">Project Instructions</div>
            <textarea
              className="min-h-[220px] w-full resize-y rounded-md border border-surface-border bg-surface p-3 text-sm text-text outline-none"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Optional instructions shared by every attached channel"
            />
            <input
              className="mt-3 h-10 w-full rounded-md border border-surface-border bg-surface px-3 text-sm text-text outline-none"
              value={promptFilePath}
              onChange={(event) => setPromptFilePath(event.target.value)}
              placeholder="Optional prompt file inside the Project root"
            />
            <button
              type="button"
              onClick={() => updateProject.mutate({ prompt, prompt_file_path: promptFilePath || null })}
              className="mt-3 inline-flex h-9 items-center gap-2 rounded-md border border-accent/40 bg-accent/15 px-3 text-sm font-semibold text-accent"
            >
              <Save size={14} />
              Save
            </button>
          </div>

          <div data-testid="project-workspace-file-scope" className="rounded-md border border-surface-border bg-surface-raised p-4">
            <div className="mb-2 text-sm font-semibold text-text">File Scope</div>
            <div className="font-mono text-sm text-text-muted">workspace://{project.workspace_id}/{root}</div>
            <div className="mt-2 text-xs text-text-dim">Project knowledge lives under .spindrel/knowledge-base. Existing channel knowledge is preserved but not migrated automatically.</div>
          </div>
        </section>

        <aside data-testid="project-workspace-attached-channels" className="rounded-md border border-surface-border bg-surface-raised p-4">
          <div className="mb-3 text-sm font-semibold text-text">Attached Channels</div>
          <div className="flex flex-col gap-2">
            {(channels ?? []).map((channel) => (
              <Link key={channel.id} to={`/channels/${channel.id}`} className="rounded-md border border-surface-border px-3 py-2 text-sm text-text no-underline hover:bg-surface-overlay">
                <div className="truncate font-medium">{channel.name}</div>
                <div className="truncate font-mono text-xs text-text-dim">{channel.bot_id}</div>
              </Link>
            ))}
            {(!channels || channels.length === 0) && <div className="text-sm text-text-muted">No channels attached.</div>}
          </div>
        </aside>
      </div>
    </div>
  );
}
