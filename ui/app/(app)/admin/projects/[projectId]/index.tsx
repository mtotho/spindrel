import { Link, useNavigate, useParams } from "react-router-dom";
import { ExternalLink, FileText, FolderOpen, Hash, Plus, Save, Terminal, Unlink, Users } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { useProject, useProjectChannels, useUpdateProject } from "@/src/api/hooks/useProjects";
import { useCreateChannel, useChannels, usePatchChannelSettings } from "@/src/api/hooks/useChannels";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useWorkspace } from "@/src/api/hooks/useWorkspaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, TabBar, TextInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ChannelPicker } from "@/src/components/shared/ChannelPicker";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { WorkspaceFileBrowserSurface } from "@/src/components/workspace/WorkspaceFileBrowserSurface";
import { useHashTab } from "@/src/hooks/useHashTab";
import type { Channel, Project } from "@/src/types/api";

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

type ProjectTab = "Files" | "Terminal" | "Settings" | "Channels";

const TABS: ProjectTab[] = ["Files", "Terminal", "Settings", "Channels"];

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

function normalizePath(path: string): string {
  return path.replace(/^\/+|\/+$/g, "");
}

function ProjectChannelsSection({
  project,
  channels,
}: {
  project: Project;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
}) {
  const navigate = useNavigate();
  const { data: allChannels = [] } = useChannels();
  const { data: bots = [] } = useAdminBots();
  const createChannel = useCreateChannel();
  const patchChannel = usePatchChannelSettings();
  const [newChannelName, setNewChannelName] = useState("");
  const [newChannelBotId, setNewChannelBotId] = useState("");
  const [selectedChannelId, setSelectedChannelId] = useState("");

  useEffect(() => {
    if (!newChannelBotId && bots.length > 0) {
      setNewChannelBotId(bots[0].id);
    }
  }, [bots, newChannelBotId]);

  const attachedIds = useMemo(() => new Set((channels ?? []).map((channel) => channel.id)), [channels]);
  const attachableChannels = useMemo(
    () => allChannels.filter((channel) => !attachedIds.has(channel.id)),
    [allChannels, attachedIds],
  );

  const attachSelected = () => {
    if (!selectedChannelId || patchChannel.isPending) return;
    patchChannel.mutate({
      channelId: selectedChannelId,
      settings: { project_id: project.id },
    }, {
      onSuccess: () => setSelectedChannelId(""),
    });
  };

  const detachChannel = (channelId: string) => {
    patchChannel.mutate({
      channelId,
      settings: { project_id: null },
    });
  };

  const createProjectChannel = () => {
    const botId = newChannelBotId || bots[0]?.id;
    if (!botId || createChannel.isPending) return;
    createChannel.mutate({
      name: newChannelName.trim() || `${project.name} channel`,
      bot_id: botId,
      project_id: project.id,
    }, {
      onSuccess: (channel) => {
        setNewChannelName("");
        navigate(`/channels/${channel.id}`);
      },
    });
  };

  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
      <Section
        title="Project Channels"
        description="Channels attached here use this Project as their working surface."
        action={
          <ActionButton
            label="Create Channel"
            icon={<Plus size={14} />}
            disabled={!newChannelBotId || createChannel.isPending}
            onPress={createProjectChannel}
          />
        }
      >
        <div data-testid="project-workspace-channel-create" className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(220px,0.8fr)]">
          <FormRow label="Channel name">
            <TextInput
              value={newChannelName}
              onChangeText={setNewChannelName}
              placeholder={`${project.name} channel`}
            />
          </FormRow>
          <FormRow label="Primary bot">
            <BotPicker
              value={newChannelBotId}
              onChange={setNewChannelBotId}
              bots={bots}
              placeholder="Select bot..."
              disabled={bots.length === 0}
            />
          </FormRow>
        </div>
      </Section>

      <Section
        title="Attached Channels"
        description="Open, inspect, or remove channels from this Project."
      >
        <div data-testid="project-workspace-attached-channels" className="flex flex-col gap-2">
          <SettingsGroupLabel
            label="Attached"
            count={channels?.length ?? 0}
            icon={<Users size={13} className="text-text-dim" />}
          />
          {(!channels || channels.length === 0) ? (
            <EmptyState message="No channels are attached to this Project." />
          ) : (
            channels.map((channel) => (
              <SettingsControlRow
                key={channel.id}
                leading={<Hash size={14} />}
                title={channel.name}
                description={channel.bot_id}
                meta={<QuietPill label="project" />}
                action={
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    <HeaderLink to={`/channels/${channel.id}`} icon={<ExternalLink size={13} />}>Open</HeaderLink>
                    <HeaderLink to={`/channels/${channel.id}/settings#agent`} icon={<Users size={13} />}>Settings</HeaderLink>
                    <ActionButton
                      label="Detach"
                      icon={<Unlink size={13} />}
                      size="small"
                      variant="secondary"
                      disabled={patchChannel.isPending}
                      onPress={() => detachChannel(channel.id)}
                    />
                  </div>
                }
              />
            ))
          )}
        </div>
      </Section>

      <Section
        title="Attach Existing Channel"
        description="Move an existing channel onto this Project workspace."
      >
        <div data-testid="project-workspace-channel-attach" className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <FormRow label="Channel">
            <ChannelPicker
              value={selectedChannelId}
              onChange={setSelectedChannelId}
              channels={attachableChannels}
              bots={bots}
              placeholder="Select channel..."
              disabled={attachableChannels.length === 0}
            />
          </FormRow>
          <ActionButton
            label="Attach"
            icon={<Plus size={14} />}
            disabled={!selectedChannelId || patchChannel.isPending}
            onPress={attachSelected}
          />
        </div>
        {attachableChannels.length === 0 && (
          <div className="mt-2">
            <EmptyState message="Every visible channel is already attached to this Project." />
          </div>
        )}
      </Section>
    </div>
  );
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading } = useProject(projectId);
  const { data: channels } = useProjectChannels(projectId);
  const { data: workspace } = useWorkspace(project?.workspace_id);
  const updateProject = useUpdateProject(projectId);
  const [tab, setTab] = useHashTab<ProjectTab>("Files", TABS);
  const [prompt, setPrompt] = useState("");
  const [promptFilePath, setPromptFilePath] = useState("");
  const [terminalPath, setTerminalPath] = useState<string | null>(null);

  useEffect(() => {
    setPrompt(project?.prompt ?? "");
    setPromptFilePath(project?.prompt_file_path ?? "");
  }, [project?.prompt, project?.prompt_file_path]);

  useEffect(() => {
    if (project?.root_path) setTerminalPath(normalizePath(project.root_path));
  }, [project?.root_path]);

  const dirty = prompt !== (project?.prompt ?? "") || promptFilePath !== (project?.prompt_file_path ?? "");
  const root = project ? normalizePath(project.root_path) : "";
  const workspaceUri = project ? `workspace://${project.workspace_id}/${root}` : "";
  const terminalCwd = project ? `workspace://${project.workspace_id}/${terminalPath || root}` : "";
  const terminalLabel = terminalPath ? `/${terminalPath}` : `/${root}`;
  const filesHref = project ? `/admin/workspaces/${project.workspace_id}/files?path=${encodeURIComponent(`/${root}`)}` : "";

  const tabItems = useMemo(() => TABS.map((key) => ({ key, label: key })), []);

  if (isLoading || !project) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }

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
            <HeaderLink to={`/admin/terminal?cwd=${encodeURIComponent(workspaceUri)}`} icon={<Terminal size={13} />}>Terminal</HeaderLink>
          </div>
        }
      />

      <div className="shrink-0 px-5 pt-3 md:px-6">
        <TabBar tabs={tabItems} active={tab} onChange={(value) => setTab(value as ProjectTab)} />
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "Files" && (
          <div data-testid="project-workspace-files" className="flex h-full min-h-0 flex-col">
            {!workspace ? (
              <div className="flex flex-1 items-center justify-center"><Spinner /></div>
            ) : (
              <WorkspaceFileBrowserSurface
                workspace={workspace}
                rootPath={root}
                rootLabel="Project"
                title={project.name}
                settingsHref={`/admin/projects/${project.id}#Settings`}
                onOpenTerminal={(path) => {
                  setTerminalPath(path || root);
                  setTab("Terminal");
                }}
              />
            )}
          </div>
        )}

        {tab === "Terminal" && (
          <div data-testid="project-workspace-terminal" className="flex h-full min-h-0 flex-col bg-[#0a0d12]">
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/10 bg-[#0d1117] px-3">
              <Terminal size={15} className="text-accent" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-semibold text-zinc-200">Terminal</div>
                <div className="truncate font-mono text-[10px] text-zinc-500">{terminalLabel}</div>
              </div>
            </div>
            <Suspense fallback={<div className="flex flex-1 items-center justify-center text-[12px] text-zinc-500">Starting terminal...</div>}>
              <TerminalPanel cwd={terminalCwd} />
            </Suspense>
          </div>
        )}

        {tab === "Settings" && (
          <div className="h-full overflow-auto">
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
            </div>
          </div>
        )}

        {tab === "Channels" && (
          <div className="h-full overflow-auto">
            <ProjectChannelsSection project={project} channels={channels} />
          </div>
        )}
      </div>
    </div>
  );
}
