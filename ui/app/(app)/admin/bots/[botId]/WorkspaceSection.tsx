import { useMemo, useState } from "react";
import { Box, Container, ExternalLink, FileText, FolderTree, Package, Plus, RefreshCw, Search, Server, Shield, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useBotSandboxStatus, useRecreateBotSandbox } from "@/src/api/hooks/useBots";
import { useWorkspaceFiles } from "@/src/api/hooks/useWorkspaces";
import { Col, FormRow, Row, SelectInput, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { SourceFileInspector } from "@/src/components/shared/SourceFileInspector";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { formatDateTime } from "@/src/utils/time";
import type { BotConfig, BotEditorData } from "@/src/types/api";

function ensureLeadingSlash(path: string): string {
  return path.startsWith("/") ? path : `/${path}`;
}

function stripLeadingSlash(path: string): string {
  return path.replace(/^\/+/, "");
}

function formatBytes(size?: number | null): string {
  if (!size || size <= 0) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function addToArray<T>(items: T[], value: T, isValid: (value: T) => boolean = Boolean as any): T[] {
  return isValid(value) ? [...items, value] : items;
}

function ChipList({
  items,
  render,
  onRemove,
  empty,
}: {
  items: any[];
  render: (item: any, index: number) => React.ReactNode;
  onRemove: (index: number) => void;
  empty: string;
}) {
  if (!items.length) return <div className="text-[12px] text-text-dim">{empty}</div>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, index) => (
        <span key={index} className="inline-flex max-w-full items-center gap-1.5 rounded-full bg-surface-overlay/40 px-2 py-1 text-[11px] text-text-muted">
          <span className="min-w-0 truncate">{render(item, index)}</span>
          <button
            type="button"
            onClick={() => onRemove(index)}
            className="shrink-0 text-danger/80 transition-colors hover:text-danger"
            aria-label="Remove item"
          >
            <Trash2 size={11} />
          </button>
        </span>
      ))}
    </div>
  );
}

function BotKnowledgeBaseSection({
  botId,
  workspaceId,
  autoRetrieval,
  onToggle,
  isHarness = false,
}: {
  botId: string;
  workspaceId?: string | null;
  autoRetrieval: boolean;
  onToggle: (value: boolean) => void;
  isHarness?: boolean;
}) {
  const navigate = useNavigate();
  const rootPath = ensureLeadingSlash(workspaceId ? `bots/${botId}/knowledge-base` : "knowledge-base");
  const { data, isLoading, refetch } = useWorkspaceFiles(workspaceId ?? undefined, rootPath);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const entries = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return [...(data?.entries ?? [])]
      .filter((entry) => !needle || `${entry.name} ${entry.display_name ?? ""} ${entry.path}`.toLowerCase().includes(needle))
      .sort((a, b) => {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
      .slice(0, 12);
  }, [data?.entries, filter]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <SettingsGroupLabel label="Bot knowledge base" icon={<FolderTree size={12} className="text-text-dim" />} />
          <p className="mt-1 max-w-[70ch] text-[12px] leading-relaxed text-text-dim">
            {isHarness
              ? "Curated files that stay with this bot. Harness turns do not currently run the normal bot-knowledge auto-RAG path; use bridge tools or the channel project directory when the harness needs these files."
              : "Curated reference docs that travel with this bot across channels. Files stay indexed either way; auto-retrieve controls whether matching excerpts are admitted before broad workspace search."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <StatusBadge label={autoRetrieval ? "auto retrieve" : "search only"} variant={autoRetrieval ? "info" : "neutral"} />
          {workspaceId && (
            <>
              <ActionButton label="Refresh" size="small" variant="secondary" icon={<RefreshCw size={12} />} onPress={() => { void refetch(); }} />
              <ActionButton
                label="Open location"
                size="small"
                variant="secondary"
                icon={<ExternalLink size={12} />}
                onPress={() => navigate(`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(rootPath)}`)}
              />
            </>
          )}
        </div>
      </div>

      <Toggle
        value={autoRetrieval}
        onChange={onToggle}
        label="Auto-retrieve bot knowledge"
        description={isHarness
          ? "Applies to normal-loop bots. Harness visibility is via filesystem/bridge tools and explicit hints."
          : "Turn this off to keep the bot knowledge base search-only."}
      />

      {!workspaceId ? (
        <EmptyState message="This bot is not attached to a shared workspace in this environment, so the inline knowledge-base browser is unavailable." />
      ) : (
        <div className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-2">
            <SettingsSearchBox value={filter} onChange={setFilter} placeholder="Filter knowledge files..." />
            {isLoading ? (
              <div className="flex justify-center rounded-md bg-surface-raised/35 p-6"><Spinner size={16} /></div>
            ) : entries.length === 0 ? (
              <EmptyState message={filter ? "No knowledge files match the filter." : "No bot knowledge files yet. Drop markdown files into this folder to index them."} />
            ) : (
              <div className="flex min-w-0 flex-col gap-1.5">
                {entries.map((entry) => {
                  const fullPath = ensureLeadingSlash(entry.path);
                  const selected = !entry.is_dir && selectedPath === fullPath;
                  return (
                    <SettingsControlRow
                      key={fullPath}
                      active={selected}
                      disabled={entry.is_dir}
                      onClick={entry.is_dir ? undefined : () => setSelectedPath(fullPath)}
                      compact
                      leading={entry.is_dir ? <FolderTree size={13} /> : <FileText size={13} />}
                      title={entry.display_name || entry.name}
                      description={stripLeadingSlash(fullPath)}
                      meta={<QuietPill label={entry.is_dir ? "folder" : formatBytes(entry.size)} />}
                    />
                  );
                })}
              </div>
            )}
          </div>
          <div className="min-w-0">
            {!selectedPath ? (
              <div className="flex h-[320px] items-center justify-center rounded-md bg-surface-raised/35 px-4 text-center text-[12px] text-text-dim">
                Select a knowledge file to preview it here.
              </div>
            ) : (
              <SourceFileInspector
                variant="panel"
                className="h-[360px]"
                target={{
                  kind: "workspace_file",
                  workspace_id: workspaceId,
                  path: selectedPath,
                  display_path: stripLeadingSlash(selectedPath),
                  owner_type: "bot",
                  owner_id: botId,
                  owner_name: "Bot knowledge",
                }}
                fallbackUrl={`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(rootPath)}`}
                onOpenFallback={(url) => navigate(url)}
                onClose={() => setSelectedPath(null)}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ContainerStatusBanner({
  sandbox,
  isRecreating,
  onRecreate,
}: {
  sandbox: { exists: boolean; status?: string | null; container_name?: string | null; container_id?: string | null; image_id?: string | null; error_message?: string | null; created_at?: string | null; last_used_at?: string | null };
  isRecreating: boolean;
  onRecreate: () => void;
}) {
  if (!sandbox.exists) {
    return (
      <SettingsControlRow
        leading={<Container size={14} />}
        title="No container yet"
        description="The sandbox will be created on first use."
        meta={<StatusBadge label="pending" variant="neutral" />}
      />
    );
  }

  const status = sandbox.status || "unknown";
  const variant = status === "running" ? "success" : status === "dead" ? "danger" : status === "creating" ? "info" : "warning";
  return (
    <SettingsControlRow
      leading={<Container size={14} />}
      title={sandbox.container_name || "Sandbox container"}
      description={
        <span className="break-words">
          {[
            sandbox.container_id ? `id ${sandbox.container_id}` : null,
            sandbox.created_at ? `created ${formatDateTime(sandbox.created_at)}` : null,
            sandbox.last_used_at ? `last used ${formatDateTime(sandbox.last_used_at)}` : null,
            sandbox.image_id ? `image ${sandbox.image_id}` : null,
          ].filter(Boolean).join(" · ")}
          {sandbox.error_message && <span className="mt-1 block text-danger">{sandbox.error_message}</span>}
        </span>
      }
      meta={<StatusBadge label={status} variant={variant} />}
      action={
        <ActionButton
          label={isRecreating ? "Recreating" : "Recreate"}
          size="small"
          variant="secondary"
          icon={<RefreshCw size={12} className={isRecreating ? "animate-spin" : ""} />}
          disabled={isRecreating}
          onPress={onRecreate}
        />
      }
    />
  );
}

export function WorkspaceSection({
  editorData,
  draft,
  update,
  isHarness = false,
}: {
  editorData: BotEditorData;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  isHarness?: boolean;
}) {
  const ws = draft.workspace || { enabled: false };
  const docker = ws.docker || {};
  const host = ws.host || {};
  const indexing = ws.indexing || {};

  const setWs = (patch: Record<string, any>) => update({ workspace: { ...ws, ...patch } });
  const setDocker = (patch: Record<string, any>) => setWs({ docker: { ...docker, ...patch } });
  const setHost = (patch: Record<string, any>) => setWs({ host: { ...host, ...patch } });
  const setIndexing = (patch: Record<string, any>) => setWs({ indexing: { ...indexing, ...patch } });

  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvVal, setNewEnvVal] = useState("");
  const [newHostPort, setNewHostPort] = useState("");
  const [newContainerPort, setNewContainerPort] = useState("");
  const [newMountHost, setNewMountHost] = useState("");
  const [newMountContainer, setNewMountContainer] = useState("");
  const [newMountMode, setNewMountMode] = useState("rw");
  const [newCmd, setNewCmd] = useState("");
  const [newCmdSubs, setNewCmdSubs] = useState("");
  const [newBlocked, setNewBlocked] = useState("");
  const [newEnvPass, setNewEnvPass] = useState("");
  const [newPattern, setNewPattern] = useState("");
  const [newSegPrefix, setNewSegPrefix] = useState("");
  const [newSegModel, setNewSegModel] = useState("");

  const inSharedWorkspace = !!draft.shared_workspace_id;
  const isExisting = !!draft.id;
  const workspaceEnabled = Boolean(ws.enabled || inSharedWorkspace);
  const isDocker = !inSharedWorkspace && ws.enabled && (ws.type || "docker") === "docker";
  const sandbox = useBotSandboxStatus(isExisting && isDocker ? draft.id : undefined, isDocker);
  const recreate = useRecreateBotSandbox(draft.id);

  const envEntries = Object.entries(docker.env || {});
  const ports: any[] = docker.ports || [];
  const mounts: any[] = docker.mounts || [];
  const commands: any[] = host.commands || [];
  const blocked: string[] = host.blocked_patterns || [];
  const envPass: string[] = host.env_passthrough || [];
  const patterns: string[] = indexing.patterns || [];
  const segments: any[] = indexing.segments || [];

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <SettingsStatGrid
        items={[
          { label: "Workspace", value: inSharedWorkspace ? "shared" : workspaceEnabled ? "standalone" : "off", tone: workspaceEnabled ? "accent" : "default" },
          { label: "Role", value: draft.shared_workspace_role || "bot" },
          { label: "Index dirs", value: segments.length + (!inSharedWorkspace ? patterns.length : 0) },
          { label: "KB mode", value: ws.bot_knowledge_auto_retrieval === false ? "search" : "auto", tone: ws.bot_knowledge_auto_retrieval === false ? "default" : "accent" },
        ]}
      />

      {inSharedWorkspace ? (
        <SettingsControlRow
          leading={<Package size={14} />}
          title={editorData.bot.shared_workspace_id || "Shared workspace"}
          description={`This bot is scoped to /workspace/bots/${draft.id || "bot-id"}/. Container settings are managed by the workspace.`}
          meta={<StatusBadge label={draft.shared_workspace_role || "member"} variant={draft.shared_workspace_role === "orchestrator" ? "purple" : "info"} />}
          action={
            <Link to={`/admin/workspaces/${draft.shared_workspace_id}`} className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-accent hover:bg-accent/[0.08]">
              Workspace <ExternalLink size={12} />
            </Link>
          }
        />
      ) : (
        <Toggle
          value={ws.enabled ?? false}
          onChange={(value) => setWs({ enabled: value })}
          label="Enable workspace tools"
          description="Adds command execution, workspace search, delegation-to-exec, and file tools for this bot."
        />
      )}

      {workspaceEnabled && (
        <>
          {!inSharedWorkspace && (
            <div className="flex flex-col gap-5">
              <div className="grid gap-3 md:grid-cols-3">
                <FormRow label="Type">
                  <SelectInput
                    value={ws.type || "docker"}
                    onChange={(value) => setWs({ type: value })}
                    options={[
                      { label: "Docker container", value: "docker" },
                      { label: "Host execution", value: "host" },
                    ]}
                  />
                </FormRow>
                <FormRow label="Timeout">
                  <TextInput value={String(ws.timeout ?? "")} onChangeText={(value) => setWs({ timeout: value ? parseInt(value, 10) : null })} placeholder="30" type="number" />
                </FormRow>
                <FormRow label="Max output bytes">
                  <TextInput value={String(ws.max_output_bytes ?? "")} onChangeText={(value) => setWs({ max_output_bytes: value ? parseInt(value, 10) : null })} placeholder="65536" type="number" />
                </FormRow>
              </div>

              {(ws.type || "docker") === "docker" && (
                <div className="flex flex-col gap-4">
                  <SettingsGroupLabel label="Docker sandbox" icon={<Container size={12} className="text-text-dim" />} />
                  {isExisting && sandbox.data && (
                    <ContainerStatusBanner
                      sandbox={sandbox.data}
                      isRecreating={recreate.isPending}
                      onRecreate={() => recreate.mutate()}
                    />
                  )}
                  <Row>
                    <Col><FormRow label="Image"><TextInput value={docker.image || ""} onChangeText={(value) => setDocker({ image: value })} placeholder="python:3.12-slim" /></FormRow></Col>
                    <Col><FormRow label="Network"><SelectInput value={docker.network || "none"} onChange={(value) => setDocker({ network: value })} options={[{ label: "none", value: "none" }, { label: "bridge", value: "bridge" }, { label: "host", value: "host" }]} /></FormRow></Col>
                  </Row>
                  <Row>
                    <Col><FormRow label="Run as user"><TextInput value={docker.user || ""} onChangeText={(value) => setDocker({ user: value })} placeholder="image default" /></FormRow></Col>
                    <Col><FormRow label="CPUs"><TextInput value={String(docker.cpus ?? "")} onChangeText={(value) => setDocker({ cpus: value ? parseFloat(value) : null })} placeholder="unlimited" type="number" /></FormRow></Col>
                    <Col><FormRow label="Memory"><TextInput value={docker.memory || ""} onChangeText={(value) => setDocker({ memory: value })} placeholder="512m" /></FormRow></Col>
                  </Row>
                  <Toggle value={docker.read_only_root ?? false} onChange={(value) => setDocker({ read_only_root: value })} label="Read-only root filesystem" />

                  <div className="flex flex-col gap-2">
                    <SettingsGroupLabel label="Environment variables" count={envEntries.length} />
                    <ChipList
                      items={envEntries}
                      empty="No container environment variables configured."
                      render={([key, value]) => <span className="font-mono">{key}=<span className="text-text-dim">{String(value)}</span></span>}
                      onRemove={(index) => {
                        const next = { ...docker.env };
                        delete next[envEntries[index][0]];
                        setDocker({ env: next });
                      }}
                    />
                    <div className="grid gap-2 md:grid-cols-[minmax(0,160px)_minmax(0,1fr)_auto]">
                      <TextInput value={newEnvKey} onChangeText={setNewEnvKey} placeholder="KEY" />
                      <TextInput value={newEnvVal} onChangeText={setNewEnvVal} placeholder="value" />
                      <ActionButton label="Add" icon={<Plus size={12} />} size="small" onPress={() => {
                        if (!newEnvKey.trim()) return;
                        setDocker({ env: { ...docker.env, [newEnvKey.trim()]: newEnvVal } });
                        setNewEnvKey("");
                        setNewEnvVal("");
                      }} />
                    </div>
                    <InfoBanner icon={<Shield size={14} />}>
                      Use <Link to="/admin/secret-values" className="font-semibold text-accent">Secrets</Link> for API keys and tokens.
                    </InfoBanner>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="flex flex-col gap-2">
                      <SettingsGroupLabel label="Port mappings" count={ports.length} />
                      <ChipList
                        items={ports}
                        empty="No extra ports exposed."
                        render={(port) => <span className="font-mono">{port.host_port ? `${port.host_port}:` : ""}{port.container_port}</span>}
                        onRemove={(index) => setDocker({ ports: ports.filter((_, itemIndex) => itemIndex !== index) })}
                      />
                      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                        <TextInput value={newHostPort} onChangeText={setNewHostPort} placeholder="host optional" />
                        <TextInput value={newContainerPort} onChangeText={setNewContainerPort} placeholder="container" />
                        <ActionButton label="Add" size="small" onPress={() => {
                          if (!newContainerPort.trim()) return;
                          setDocker({ ports: [...ports, { host_port: newHostPort.trim(), container_port: newContainerPort.trim() }] });
                          setNewHostPort("");
                          setNewContainerPort("");
                        }} />
                      </div>
                    </div>
                    <div className="flex flex-col gap-2">
                      <SettingsGroupLabel label="Extra mounts" count={mounts.length} />
                      <ChipList
                        items={mounts}
                        empty="Workspace root is still mounted at /workspace."
                        render={(mount) => <span className="font-mono">{mount.host_path} : {mount.container_path} : {mount.mode || "rw"}</span>}
                        onRemove={(index) => setDocker({ mounts: mounts.filter((_, itemIndex) => itemIndex !== index) })}
                      />
                      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_80px_auto]">
                        <TextInput value={newMountHost} onChangeText={setNewMountHost} placeholder="host path" />
                        <TextInput value={newMountContainer} onChangeText={setNewMountContainer} placeholder="container path" />
                        <SelectInput value={newMountMode} onChange={setNewMountMode} options={[{ label: "rw", value: "rw" }, { label: "ro", value: "ro" }]} />
                        <ActionButton label="Add" size="small" onPress={() => {
                          if (!newMountHost.trim() || !newMountContainer.trim()) return;
                          setDocker({ mounts: [...mounts, { host_path: newMountHost.trim(), container_path: newMountContainer.trim(), mode: newMountMode }] });
                          setNewMountHost("");
                          setNewMountContainer("");
                          setNewMountMode("rw");
                        }} />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {ws.type === "host" && (
                <div className="flex flex-col gap-4">
                  <SettingsGroupLabel label="Host execution" icon={<Server size={12} className="text-text-dim" />} />
                  <FormRow label="Custom root"><TextInput value={host.root || ""} onChangeText={(value) => setHost({ root: value })} placeholder="auto: ~/.agent-workspaces/<bot-id>/" /></FormRow>
                  <div className="grid gap-4 lg:grid-cols-3">
                    <div className="flex flex-col gap-2">
                      <SettingsGroupLabel label="Allowed commands" count={commands.length} />
                      <ChipList
                        items={commands}
                        empty="No commands configured."
                        render={(command) => <span className="font-mono">{command.name} <span className="text-text-dim">{command.subcommands?.length ? command.subcommands.join(", ") : "(all)"}</span></span>}
                        onRemove={(index) => setHost({ commands: commands.filter((_, itemIndex) => itemIndex !== index) })}
                      />
                      <TextInput value={newCmd} onChangeText={setNewCmd} placeholder="binary" />
                      <TextInput value={newCmdSubs} onChangeText={setNewCmdSubs} placeholder="subcommands comma-separated" />
                      <ActionButton label="Add command" size="small" onPress={() => {
                        if (!newCmd.trim()) return;
                        const subcommands = newCmdSubs.trim().split(",").map((value) => value.trim()).filter(Boolean);
                        setHost({ commands: [...commands, { name: newCmd.trim(), subcommands }] });
                        setNewCmd("");
                        setNewCmdSubs("");
                      }} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <SettingsGroupLabel label="Blocked patterns" count={blocked.length} />
                      <ChipList items={blocked} empty="No blocked regex patterns." render={(item) => <span className="font-mono">{item}</span>} onRemove={(index) => setHost({ blocked_patterns: blocked.filter((_, itemIndex) => itemIndex !== index) })} />
                      <TextInput value={newBlocked} onChangeText={setNewBlocked} placeholder="regex pattern" />
                      <ActionButton label="Add pattern" size="small" onPress={() => {
                        setHost({ blocked_patterns: addToArray(blocked, newBlocked.trim()) });
                        setNewBlocked("");
                      }} />
                    </div>
                    <div className="flex flex-col gap-2">
                      <SettingsGroupLabel label="Env passthrough" count={envPass.length} />
                      <ChipList items={envPass} empty="No environment variables passed through." render={(item) => <span className="font-mono">{item}</span>} onRemove={(index) => setHost({ env_passthrough: envPass.filter((_, itemIndex) => itemIndex !== index) })} />
                      <TextInput value={newEnvPass} onChangeText={setNewEnvPass} placeholder="ENV_VAR_NAME" />
                      <ActionButton label="Add env" size="small" onPress={() => {
                        setHost({ env_passthrough: addToArray(envPass, newEnvPass.trim()) });
                        setNewEnvPass("");
                      }} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {draft.memory_scheme === "workspace-files" && (
            <InfoBanner icon={<Box size={14} />}>
              {isHarness ? (
                <>
                  Harness turns receive a workspace-files memory hint pointing at this bot workspace. The channel project directory, if set, only changes execution CWD.
                </>
              ) : (
                <>
                  Memory files under <span className="font-mono">memory/**/*.md</span> are indexed automatically and do not need a manual segment.
                </>
              )}
            </InfoBanner>
          )}

          {draft.id ? (
            <BotKnowledgeBaseSection
              botId={draft.id}
              workspaceId={draft.shared_workspace_id}
              autoRetrieval={ws.bot_knowledge_auto_retrieval !== false}
              onToggle={(value) => setWs({ bot_knowledge_auto_retrieval: value })}
              isHarness={isHarness}
            />
          ) : (
            <EmptyState message="Save the bot once to create its knowledge-base folder and retrieval settings." />
          )}

          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <SettingsGroupLabel label="Workspace file indexing" icon={<Search size={12} className="text-text-dim" />} />
              <div className="flex flex-wrap items-center gap-3">
                <Toggle value={indexing.enabled !== false} onChange={(value) => setIndexing({ enabled: value })} label="Enable" />
                {indexing.enabled !== false && <Toggle value={indexing.watch !== false} onChange={(value) => setIndexing({ watch: value })} label="Watch" />}
              </div>
            </div>

            {indexing.enabled !== false && (
              <>
                <InfoBanner>
                  {inSharedWorkspace
                    ? "Add directory segments to index specific workspace paths for retrieval. Shared workspaces index only configured directories by default."
                    : "Add patterns and optional segments to control what standalone workspace files enter retrieval."}
                </InfoBanner>

                <div className="flex flex-col gap-2">
                  <SettingsGroupLabel label={inSharedWorkspace ? "Indexed directories" : "Segments"} count={segments.length} />
                  <ChipList
                    items={segments}
                    empty={inSharedWorkspace ? "No directories configured; only memory files are indexed." : "No per-directory segment overrides."}
                    render={(segment) => (
                      <span className="font-mono">
                        {segment.path_prefix}
                        {segment.embedding_model && <span className="text-text-dim"> · {segment.embedding_model}</span>}
                        {segment.patterns?.length ? <span className="text-text-dim"> · {segment.patterns.length} patterns</span> : null}
                      </span>
                    )}
                    onRemove={(index) => setIndexing({ segments: segments.filter((_, itemIndex) => itemIndex !== index) })}
                  />
                  <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                    <TextInput value={newSegPrefix} onChangeText={setNewSegPrefix} placeholder={inSharedWorkspace ? "directory, e.g. common/" : "path prefix, e.g. src/"} />
                    <TextInput value={newSegModel} onChangeText={setNewSegModel} placeholder="embedding model optional" />
                    <ActionButton label={inSharedWorkspace ? "Add directory" : "Add segment"} size="small" onPress={() => {
                      if (!newSegPrefix.trim()) return;
                      const segment: Record<string, any> = { path_prefix: newSegPrefix.trim() };
                      if (newSegModel.trim()) segment.embedding_model = newSegModel.trim();
                      setIndexing({ segments: [...segments, segment] });
                      setNewSegPrefix("");
                      setNewSegModel("");
                    }} />
                  </div>
                </div>

                {!inSharedWorkspace && (
                  <div className="flex flex-col gap-2">
                    <SettingsGroupLabel label="Indexed file patterns" count={patterns.length} />
                    <ChipList
                      items={patterns}
                      empty="No file patterns configured beyond memory."
                      render={(pattern) => <span className="font-mono">{pattern}</span>}
                      onRemove={(index) => setIndexing({ patterns: patterns.filter((_, itemIndex) => itemIndex !== index) })}
                    />
                    <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                      <TextInput value={newPattern} onChangeText={setNewPattern} placeholder="docs/**/*.md" />
                      <ActionButton label="Add pattern" size="small" onPress={() => {
                        setIndexing({ patterns: addToArray(patterns, newPattern.trim()) });
                        setNewPattern("");
                      }} />
                    </div>
                  </div>
                )}

                <Row>
                  <Col><FormRow label="Similarity threshold"><TextInput value={String(indexing.similarity_threshold ?? "")} onChangeText={(value) => setIndexing({ similarity_threshold: value ? parseFloat(value) : null })} placeholder="server default" type="number" /></FormRow></Col>
                  <Col><FormRow label="Top-K results"><TextInput value={String(indexing.top_k ?? "")} onChangeText={(value) => setIndexing({ top_k: value ? parseInt(value, 10) : null })} placeholder="8" type="number" /></FormRow></Col>
                  <Col><FormRow label="Cooldown"><TextInput value={String(indexing.cooldown_seconds ?? "")} onChangeText={(value) => setIndexing({ cooldown_seconds: value ? parseInt(value, 10) : null })} placeholder="300" type="number" /></FormRow></Col>
                  <Col><FormRow label="Embedding model"><LlmModelDropdown value={indexing.embedding_model ?? ""} onChange={(value) => setIndexing({ embedding_model: value || null })} placeholder="server default" variant="embedding" /></FormRow></Col>
                </Row>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
