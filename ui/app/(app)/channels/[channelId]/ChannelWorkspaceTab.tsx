import { Spinner } from "@/src/components/shared/Spinner";
import { useMemo, useState } from "react";
import {
  BookOpen,
  ChevronRight,
  ExternalLink,
  FileText,
  FolderClosed,
  FolderSearch,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import {
  Section,
  EmptyState,
  TextInput,
  FormRow,
  SelectInput,
  Row,
  Col,
} from "@/src/components/shared/FormControls";
import {
  ActionButton,
  AdvancedSection,
  SettingsControlRow,
} from "@/src/components/shared/SettingsControls";
import { WorkspaceSchemaEditor } from "@/src/components/shared/WorkspaceSchemaEditor";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  useWorkspaceFileContent,
  useWorkspaceFiles,
} from "@/src/api/hooks/useWorkspaces";
import { apiFetch } from "@/src/api/client";
import type { ChannelSettings, WorkspaceFileEntry } from "@/src/types/api";

type IndexSegment = NonNullable<ChannelSettings["index_segments"]>[number];
type SegmentDefaults = NonNullable<ChannelSettings["index_segment_defaults"]>;
const KB_FOLDER_NAME = "knowledge-base";

function ensureLeadingSlash(path: string): string {
  return path.startsWith("/") ? path : `/${path}`;
}

function dirForApi(path: string): string {
  if (!path || path === "/") return "/";
  return ensureLeadingSlash(path);
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

function relativeToRoot(path: string, rootPath: string): string {
  const normalizedRoot = stripLeadingSlash(rootPath).replace(/\/+$/, "");
  const normalizedPath = stripLeadingSlash(path).replace(/\/+$/, "");
  if (normalizedPath === normalizedRoot) return "/";
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return normalizedPath;
}

function buildBreadcrumbs(path: string, rootPath: string): Array<{ label: string; path: string }> {
  const relative = relativeToRoot(path, rootPath);
  if (relative === "/") return [{ label: KB_FOLDER_NAME, path: rootPath }];
  const parts = relative.split("/").filter(Boolean);
  const crumbs = [{ label: KB_FOLDER_NAME, path: rootPath }];
  let current = stripLeadingSlash(rootPath);
  for (const part of parts) {
    current = `${current}/${part}`;
    crumbs.push({ label: part, path: ensureLeadingSlash(current) });
  }
  return crumbs;
}

function FileViewer({ workspaceId, path }: { workspaceId: string; path: string }) {
  const { data, isLoading } = useWorkspaceFileContent(workspaceId, path);

  if (isLoading) {
    return (
      <div className="flex justify-center p-4">
        <Spinner />
      </div>
    );
  }

  if (!data) return <span className="block p-4 text-[12px] text-text-dim">File not found</span>;

  return (
    <div className="max-h-[400px] overflow-auto rounded-md bg-surface-raised/40 p-3">
      <div className="mb-2 font-mono text-[11px] font-semibold text-text-dim">{path}</div>
      <pre className="m-0 whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-text">
        {data.content}
      </pre>
    </div>
  );
}

function InlineLink({
  to,
  children,
}: {
  to: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      className="inline-flex min-h-[32px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
    >
      <ExternalLink size={12} />
      {children}
    </Link>
  );
}

function KnowledgeBaseSection({
  workspaceId,
  channelId,
  botId,
  sharedWorkspaceId,
  botKnowledgeAutoRetrieval,
  selectedPath,
  onSelectPath,
}: {
  workspaceId?: string;
  channelId: string;
  botId?: string | null;
  sharedWorkspaceId?: string | null;
  botKnowledgeAutoRetrieval?: boolean;
  selectedPath: string | null;
  onSelectPath: (path: string | null) => void;
}) {
  const rootPath = `/channels/${channelId}/${KB_FOLDER_NAME}`;
  const [currentPath, setCurrentPath] = useState(rootPath);
  const { data, isLoading, refetch } = useWorkspaceFiles(workspaceId, dirForApi(currentPath));

  const entries = useMemo(() => {
    const rawEntries = data?.entries ?? [];
    return [...rawEntries].sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [data?.entries]);

  const folderCount = entries.filter((entry) => entry.is_dir).length;
  const fileCount = entries.length - folderCount;
  const breadcrumbs = useMemo(() => buildBreadcrumbs(currentPath, rootPath), [currentPath, rootPath]);
  const parentPath = breadcrumbs.length > 1 ? breadcrumbs[breadcrumbs.length - 2].path : null;
  const botKnowledgePath = botId
    ? (sharedWorkspaceId ? `bots/${botId}/${KB_FOLDER_NAME}/` : `${KB_FOLDER_NAME}/`)
    : null;

  const guideRows = [
    ["Channel knowledge", "Auto-indexed and channel-scoped. The bot sees matching excerpts, not the whole folder."],
    ["Bot knowledge", botKnowledgeAutoRetrieval === false
      ? "Bot-wide docs are searchable only for this bot."
      : "Bot-wide docs are auto-retrieved before broad workspace search."],
    ["Tools", "`search_channel_knowledge` for this folder. `search_bot_knowledge` for reusable bot facts."],
    ["Best fit", "Stable reference material: decisions, runbooks, specs, glossaries, and operating notes."],
  ] as const;

  return (
    <Section
      title="Knowledge Base"
      description="This channel's `knowledge-base/` is the durable reference layer for room-specific facts. It is auto-indexed, channel-scoped, and used by semantic retrieval plus the narrow knowledge search tools."
      action={workspaceId ? (
        <InlineLink to={`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(rootPath)}`}>
          Open KB in workspace
        </InlineLink>
      ) : undefined}
    >
      <div className="flex flex-col gap-5">
        <SettingsControlRow className="flex items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent/10">
            <BookOpen size={17} className="text-accent" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[13px] font-semibold text-text">
              channels/{channelId}/{KB_FOLDER_NAME}/
            </div>
            <div className="mt-0.5 text-[11px] text-text-dim">
              Indexed recursively. Relevant excerpts are pulled into channel context automatically.
            </div>
          </div>
        </SettingsControlRow>

        {botId && botKnowledgePath && (
          <SettingsControlRow className="flex flex-wrap items-center gap-3">
            <div className="min-w-[260px] flex-1">
              <div className="text-[12px] font-semibold text-text">Bot knowledge layer</div>
              <div className="mt-0.5 text-[11px] text-text-dim">
                <span className="font-mono text-text-muted">{botKnowledgePath}</span>
                {" · "}
                {botKnowledgeAutoRetrieval === false ? "Search only" : "Auto-retrieved + searchable"}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <InlineLink to={`/admin/bots/${botId}`}>Bot workspace</InlineLink>
              {workspaceId && (
                <InlineLink to={`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(`/${botKnowledgePath.replace(/\/$/, "")}`)}`}>
                  Open bot KB
                </InlineLink>
              )}
            </div>
          </SettingsControlRow>
        )}

        <div className="grid gap-x-8 gap-y-2 md:grid-cols-2">
          {guideRows.map(([label, body]) => (
            <div key={label} className="grid grid-cols-[128px_minmax(0,1fr)] gap-3 py-1">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">{label}</div>
              <div className="text-[12px] leading-relaxed text-text-dim">{body}</div>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-3 rounded-md bg-surface-raised/30 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-text">Contents</div>
              <div className="mt-0.5 text-[11px] text-text-dim">
                {folderCount} folder{folderCount === 1 ? "" : "s"} · {fileCount} file{fileCount === 1 ? "" : "s"} in {breadcrumbs[breadcrumbs.length - 1]?.label ?? KB_FOLDER_NAME}
              </div>
            </div>
            {workspaceId && (
              <ActionButton
                label="Refresh"
                variant="secondary"
                size="small"
                onPress={() => { void refetch(); }}
                icon={<RefreshCw size={13} />}
              />
            )}
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {breadcrumbs.map((crumb, index) => {
              const isActive = index === breadcrumbs.length - 1;
              return (
                <span key={crumb.path} className="inline-flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      setCurrentPath(crumb.path);
                      onSelectPath(null);
                    }}
                    disabled={isActive}
                    className={`font-mono text-[12px] transition-colors ${isActive ? "cursor-default text-text" : "text-text-dim hover:text-accent"}`}
                  >
                    {crumb.label}
                  </button>
                  {index < breadcrumbs.length - 1 && <ChevronRight size={12} className="text-text-dim" />}
                </span>
              );
            })}
          </div>

          {parentPath && (
            <ActionButton
              label="Up one level"
              onPress={() => {
                setCurrentPath(parentPath);
                onSelectPath(null);
              }}
              variant="ghost"
              size="small"
              icon={<ChevronRight size={12} className="rotate-180" />}
            />
          )}

          {!workspaceId ? (
            <EmptyState message="This channel does not currently have a workspace attached, so the knowledge base contents cannot be browsed here." />
          ) : isLoading ? (
            <div className="flex justify-center p-6">
              <Spinner />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState message="No knowledge-base files yet. Drop reference docs here and they will start indexing automatically." />
          ) : (
            <div className="flex flex-col gap-1.5">
              {entries.map((entry: WorkspaceFileEntry) => {
                const fullPath = ensureLeadingSlash(entry.path);
                const isSelected = !entry.is_dir && selectedPath === fullPath;
                const metaLabel = entry.is_dir
                  ? relativeToRoot(entry.path, rootPath)
                  : `${relativeToRoot(entry.path, rootPath)} · ${formatBytes(entry.size)}`;
                return (
                  <SettingsControlRow
                    key={fullPath}
                    active={isSelected}
                    onClick={() => {
                      if (entry.is_dir) {
                        setCurrentPath(fullPath);
                        onSelectPath(null);
                      } else {
                        onSelectPath(fullPath);
                      }
                    }}
                    className="flex items-center gap-2.5"
                  >
                    {entry.is_dir ? (
                      <FolderClosed size={16} className="shrink-0 text-accent" />
                    ) : (
                      <FileText size={16} className="shrink-0 text-text-dim" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium text-text">
                        {entry.display_name || entry.name}
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-text-dim">{metaLabel}</div>
                    </div>
                    <span className="shrink-0 text-[11px] text-text-muted">
                      {entry.is_dir ? "Open" : formatBytes(entry.size)}
                    </span>
                  </SettingsControlRow>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

function DefaultHint({ value, defaultValue, label }: { value: string | undefined | null; defaultValue: string; label?: string }) {
  if (value) return null;
  return (
    <span className="text-[10px] italic text-text-dim">
      {label ? `${label}: ` : ""}{defaultValue}
    </span>
  );
}

function IndexedDirectoriesSection({
  segments,
  onChange,
  channelId,
  defaults,
}: {
  segments: IndexSegment[];
  onChange: (segs: IndexSegment[]) => void;
  channelId: string;
  defaults: SegmentDefaults | null | undefined;
}) {
  const [adding, setAdding] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [newPatterns, setNewPatterns] = useState("");
  const [newModel, setNewModel] = useState("");
  const [newTopK, setNewTopK] = useState("");
  const [newThreshold, setNewThreshold] = useState("");

  const reindexMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/reindex-segments`, { method: "POST" }),
    onSuccess: () => { setTimeout(() => reindexMutation.reset(), 3000); },
    onError: () => { setTimeout(() => reindexMutation.reset(), 5000); },
  });

  const defaultPatterns = defaults?.patterns?.join(", ") ?? "**/*.py, **/*.md, **/*.yaml";
  const defaultModel = defaults?.embedding_model ?? "text-embedding-3-small";
  const defaultThreshold = defaults?.similarity_threshold ?? 0.3;
  const defaultTopK = defaults?.top_k ?? 8;

  const handleAdd = () => {
    const trimmed = newPath.trim().replace(/^\/+|\/+$/g, "");
    if (!trimmed) return;
    const seg: IndexSegment = { path_prefix: trimmed };
    if (newPatterns.trim()) seg.patterns = newPatterns.split(",").map((p) => p.trim()).filter(Boolean);
    if (newModel.trim()) seg.embedding_model = newModel.trim();
    if (newTopK.trim()) {
      const parsed = parseInt(newTopK.trim(), 10);
      if (!Number.isNaN(parsed) && parsed > 0) seg.top_k = parsed;
    }
    if (newThreshold.trim()) {
      const parsed = parseFloat(newThreshold.trim());
      if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) seg.similarity_threshold = parsed;
    }
    onChange([...segments, seg]);
    setNewPath("");
    setNewPatterns("");
    setNewModel("");
    setNewTopK("");
    setNewThreshold("");
    setAdding(false);
  };

  const handleRemove = (idx: number) => {
    onChange(segments.filter((_, i) => i !== idx));
  };

  return (
    <Section
      title="Custom Indexed Directories"
      description="Advanced — for external repos or when you need a non-default embedding model per prefix. Most channels only need the Knowledge Base above; files you drop there are indexed automatically."
      action={
        <ActionButton
          label={reindexMutation.isPending ? "Reindexing..." : "Reindex"}
          onPress={() => reindexMutation.mutate()}
          disabled={reindexMutation.isPending || segments.length === 0}
          variant="secondary"
          size="small"
          icon={<RefreshCw size={12} />}
        />
      }
    >
      <div className="flex flex-col gap-2">
        {segments.length === 0 && !adding && (
          <EmptyState message="No indexed directories configured. Add one to enable automatic semantic retrieval from those files." />
        )}

        {segments.map((seg, i) => (
          <SettingsControlRow key={i} className="flex items-center gap-2">
            <FolderSearch size={14} className="shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-mono text-[13px] font-medium text-text">{seg.path_prefix}</div>
              <div className="truncate text-[11px] text-text-dim">
                patterns: {seg.patterns?.join(", ") || defaultPatterns}
                {" · "}
                model: {seg.embedding_model || defaultModel}
                {" · "}
                top_k: {seg.top_k ?? defaultTopK}
                {" · "}
                threshold: {seg.similarity_threshold ?? defaultThreshold}
              </div>
            </div>
            <ActionButton
              label="Remove"
              onPress={() => handleRemove(i)}
              variant="danger"
              size="small"
              icon={<X size={13} />}
            />
          </SettingsControlRow>
        ))}

        {adding ? (
          <div className="flex flex-col gap-3 rounded-md bg-surface-raised/35 p-3">
            <FormRow label="Path prefix" description="Relative to channel workspace, e.g. data/repo">
              <TextInput value={newPath} onChangeText={setNewPath} placeholder="data/repo" />
            </FormRow>
            <FormRow label="Patterns (optional)" description="Comma-separated globs. Prefix with ! to exclude.">
              <TextInput value={newPatterns} onChangeText={setNewPatterns} placeholder={defaultPatterns} />
              <DefaultHint value={newPatterns} defaultValue={defaultPatterns} label="Inherited" />
            </FormRow>
            <FormRow label="Embedding model (optional)">
              <LlmModelDropdown
                value={newModel}
                onChange={setNewModel}
                placeholder={defaultModel}
                allowClear
                variant="embedding"
              />
              <DefaultHint value={newModel} defaultValue={defaultModel} label="Inherited" />
            </FormRow>
            <Row>
              <Col>
                <FormRow label="Top K (optional)" description="Max results returned">
                  <TextInput value={newTopK} onChangeText={setNewTopK} placeholder={String(defaultTopK)} />
                  <DefaultHint value={newTopK} defaultValue={String(defaultTopK)} label="Inherited" />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Similarity threshold (optional)" description="Min cosine similarity (0-1)">
                  <TextInput value={newThreshold} onChangeText={setNewThreshold} placeholder={String(defaultThreshold)} />
                  <DefaultHint value={newThreshold} defaultValue={String(defaultThreshold)} label="Inherited" />
                </FormRow>
              </Col>
            </Row>
            <div className="flex flex-wrap gap-2">
              <ActionButton label="Add" onPress={handleAdd} disabled={!newPath.trim()} size="small" />
              <ActionButton
                label="Cancel"
                onPress={() => {
                  setAdding(false);
                  setNewPath("");
                  setNewPatterns("");
                  setNewModel("");
                  setNewTopK("");
                  setNewThreshold("");
                }}
                variant="secondary"
                size="small"
              />
            </div>
          </div>
        ) : (
          <ActionButton
            label="Add Directory"
            onPress={() => setAdding(true)}
            size="small"
            icon={<Plus size={14} />}
          />
        )}

        {defaults && segments.length === 0 && !adding && (
          <div className="px-1 text-[10px] leading-relaxed text-text-dim">
            Defaults from bot workspace config: top_k={defaultTopK}, threshold={defaultThreshold}, model={defaultModel}
          </div>
        )}

        {reindexMutation.isSuccess && (
          <span className="text-[11px] text-success">Reindex complete</span>
        )}
        {reindexMutation.isError && (
          <span className="text-[11px] text-danger">
            Reindex failed: {(reindexMutation.error as Error)?.message || "Unknown error"}
          </span>
        )}
      </div>
    </Section>
  );
}

export function ChannelWorkspaceTab({
  form,
  patch,
  channelId,
  workspaceId,
  botId,
  sharedWorkspaceId,
  botKnowledgeAutoRetrieval,
  indexSegmentDefaults,
  hasSharedWorkspace,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
  workspaceId?: string;
  botId?: string | null;
  indexSegmentDefaults?: SegmentDefaults | null;
  hasSharedWorkspace?: boolean;
  sharedWorkspaceId?: string | null;
  botKnowledgeAutoRetrieval?: boolean;
}) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  return (
    <>
      <KnowledgeBaseSection
        workspaceId={workspaceId}
        channelId={channelId}
        botId={botId}
        sharedWorkspaceId={sharedWorkspaceId}
        botKnowledgeAutoRetrieval={botKnowledgeAutoRetrieval}
        selectedPath={selectedPath}
        onSelectPath={setSelectedPath}
      />

      {selectedPath && workspaceId && (
        <Section title="File Preview" description="Preview the selected knowledge-base file without leaving settings.">
          <FileViewer workspaceId={workspaceId} path={selectedPath} />
        </Section>
      )}

      <AdvancedSection title="Advanced Workspace Settings">
        <Section
          title="Organization Template"
          description="Optional template defining how workspace files should be structured. Integrations with capabilities teach file organization automatically."
        >
          <WorkspaceSchemaEditor
            templateId={form.workspace_schema_template_id ?? null}
            schemaContent={form.workspace_schema_content ?? null}
            onTemplateChange={(id) => patch("workspace_schema_template_id", id)}
            onContentChange={(content) => patch("workspace_schema_content", content)}
          />
        </Section>

        <IndexedDirectoriesSection
          segments={form.index_segments ?? []}
          onChange={(segs) => patch("index_segments", segs)}
          channelId={channelId}
          defaults={indexSegmentDefaults}
        />

        {hasSharedWorkspace && (
          <Section title="Shared Workspace Overrides" description="Override workspace-level settings for this channel. These control features inherited from the bot's shared workspace.">
            <FormRow label="Workspace base prompt" description="common/prompts/base.md from the workspace is added after the global base prompt. Per-bot additions concatenate after.">
              <SelectInput
                value={form.workspace_base_prompt_enabled == null ? "inherit" : form.workspace_base_prompt_enabled ? "on" : "off"}
                options={[
                  { label: "Inherit from workspace", value: "inherit" },
                  { label: "Enabled", value: "on" },
                  { label: "Disabled", value: "off" },
                ]}
                onChange={(v) => patch("workspace_base_prompt_enabled" as any, v === "inherit" ? null : v === "on")}
              />
            </FormRow>
          </Section>
        )}
      </AdvancedSection>
    </>
  );
}
