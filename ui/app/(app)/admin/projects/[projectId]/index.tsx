import { Link, useParams } from "react-router-dom";
import { ExternalLink, FileText, FolderOpen, Save, Terminal, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { useProject, useProjectChannels, useUpdateProject } from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, TextInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

function HeaderLink({ to, children, icon }: { to: string; children: React.ReactNode; icon: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text"
    >
      {icon}
      {children}
    </Link>
  );
}

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
  const workspaceUri = `workspace://${project.workspace_id}/${root}`;
  const terminalHref = `/admin/terminal?cwd=${encodeURIComponent(workspaceUri)}`;
  const filesHref = `/admin/workspaces/${project.workspace_id}/files?path=${encodeURIComponent(`/${root}`)}`;
  const dirty = prompt !== (project.prompt ?? "") || promptFilePath !== (project.prompt_file_path ?? "");

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        title={project.name}
        subtitle={`/${project.root_path}`}
        backTo="/admin/projects"
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <HeaderLink to={filesHref} icon={<ExternalLink size={13} />}>Files</HeaderLink>
            <HeaderLink to={terminalHref} icon={<Terminal size={13} />}>Terminal</HeaderLink>
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
          <Section
            title="Instructions"
            description="Shared turn guidance for channels attached to this Project."
            action={
              <div className="flex items-center gap-2">
                <SaveStatusPill
                  tone={updateProject.isPending ? "pending" : dirty ? "dirty" : "idle"}
                  label={updateProject.isPending ? "Saving" : "Unsaved"}
                />
                <ActionButton
                  label="Save"
                  icon={<Save size={14} />}
                  disabled={!dirty || updateProject.isPending}
                  onPress={() => updateProject.mutate({ prompt, prompt_file_path: promptFilePath.trim() || null })}
                />
              </div>
            }
          >
            <div data-testid="project-workspace-instructions" className="flex flex-col gap-3">
              <PromptEditor
                value={prompt}
                onChange={setPrompt}
                label="Project instructions"
                placeholder="Optional instructions shared by every attached channel..."
                helpText="Applied before channel-level prompt content for Project-bound turns."
                rows={7}
                fieldType="project_prompt"
                generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
              />
              <FormRow label="Prompt file" description="Optional Project-root relative file that can own these instructions later.">
                <TextInput
                  value={promptFilePath}
                  onChangeText={setPromptFilePath}
                  placeholder=".spindrel/project-prompt.md"
                />
              </FormRow>
            </div>
          </Section>

          <Section
            title="Workspace Scope"
            description="Runtime cwd, file browser, terminal, search, and harness turns resolve from this root."
          >
            <div data-testid="project-workspace-file-scope" className="grid gap-2 md:grid-cols-2">
              <SettingsControlRow
                leading={<FolderOpen size={14} />}
                title="Root URI"
                description={<span className="font-mono">{workspaceUri}</span>}
                meta={<QuietPill label={project.workspace_id} maxWidthClass="max-w-[180px]" />}
                action={<HeaderLink to={filesHref} icon={<ExternalLink size={13} />}>Open location</HeaderLink>}
              />
              <SettingsControlRow
                leading={<FileText size={14} />}
                title="Project knowledge"
                description={<span className="font-mono">/{root}/.spindrel/knowledge-base</span>}
                meta={<QuietPill label="not migrated" />}
              />
            </div>
          </Section>

          <Section
            title="Attached Channels"
            description="Channels using this Project root for their working surface."
          >
            <div data-testid="project-workspace-attached-channels" className="flex flex-col gap-2">
              <SettingsGroupLabel
                label="Channels"
                count={channels?.length ?? 0}
                icon={<Users size={13} className="text-text-dim" />}
              />
              {(!channels || channels.length === 0) ? (
                <EmptyState message="No channels are attached to this Project." />
              ) : (
                channels.map((channel) => (
                  <SettingsControlRow
                    key={channel.id}
                    leading={<Users size={14} />}
                    title={channel.name}
                    description={channel.bot_id}
                    meta={<QuietPill label="attached" />}
                    action={<HeaderLink to={`/channels/${channel.id}`} icon={<ExternalLink size={13} />}>Open</HeaderLink>}
                  />
                ))
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
