import { useMemo, useState } from "react";
import { Box, ExternalLink, FileText, FolderTree, Package, RefreshCw, Search, Trash2 } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { useWorkspaceFiles } from "@/src/api/hooks/useWorkspaces";
import { Col, FormRow, Row, TextInput, Toggle } from "@/src/components/shared/FormControls";
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
  const indexing = ws.indexing || {};

  const setWs = (patch: Record<string, any>) => update({ workspace: { ...ws, ...patch } });
  const setIndexing = (patch: Record<string, any>) => setWs({ indexing: { ...indexing, ...patch } });

  const [newPattern, setNewPattern] = useState("");
  const [newSegPrefix, setNewSegPrefix] = useState("");
  const [newSegModel, setNewSegModel] = useState("");

  const defaultWorkspaceId = editorData.default_shared_workspace_id ?? null;
  const effectiveWorkspaceId = draft.shared_workspace_id ?? defaultWorkspaceId;
  const workspacePending = !draft.shared_workspace_id;
  const patterns: string[] = indexing.patterns || [];
  const segments: any[] = indexing.segments || [];

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <SettingsStatGrid
        items={[
          { label: "Workspace", value: workspacePending ? "pending shared" : "shared", tone: "accent" },
          { label: "Role", value: draft.shared_workspace_role || "member" },
          { label: "Index dirs", value: segments.length },
          { label: "KB mode", value: ws.bot_knowledge_auto_retrieval === false ? "search" : "auto", tone: ws.bot_knowledge_auto_retrieval === false ? "default" : "accent" },
        ]}
      />

      <SettingsControlRow
        leading={<Package size={14} />}
        title={editorData.default_shared_workspace_name || "Default shared workspace"}
        description={`This bot uses /workspace/bots/${draft.id || "bot-id"}/ inside the shared workspace. New bots are enrolled when saved.`}
        meta={<StatusBadge label={workspacePending ? "enrolls on save" : (draft.shared_workspace_role || "member")} variant={draft.shared_workspace_role === "orchestrator" ? "purple" : "info"} />}
        action={effectiveWorkspaceId ? (
          <Link to={`/admin/workspaces/${effectiveWorkspaceId}`} className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-accent hover:bg-accent/[0.08]">
            Workspace <ExternalLink size={12} />
          </Link>
        ) : undefined}
      />

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
          workspaceId={effectiveWorkspaceId}
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
              Add directory segments to index specific shared-workspace paths for retrieval. Bot memory and knowledge-base files keep their convention-based indexing.
            </InfoBanner>

            <div className="flex flex-col gap-2">
              <SettingsGroupLabel label="Indexed directories" count={segments.length} />
              <ChipList
                items={segments}
                empty="No directories configured; only memory and knowledge-base files are indexed."
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
                <TextInput value={newSegPrefix} onChangeText={setNewSegPrefix} placeholder="directory, e.g. common/" />
                <TextInput value={newSegModel} onChangeText={setNewSegModel} placeholder="embedding model optional" />
                <ActionButton label="Add directory" size="small" onPress={() => {
                  if (!newSegPrefix.trim()) return;
                  const segment: Record<string, any> = { path_prefix: newSegPrefix.trim() };
                  if (newSegModel.trim()) segment.embedding_model = newSegModel.trim();
                  setIndexing({ segments: [...segments, segment] });
                  setNewSegPrefix("");
                  setNewSegModel("");
                }} />
              </div>
            </div>

            {patterns.length > 0 && (
              <div className="flex flex-col gap-2">
                <SettingsGroupLabel label="Legacy indexed file patterns" count={patterns.length} />
                <ChipList
                  items={patterns}
                  empty="No legacy file patterns configured."
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
    </div>
  );
}
