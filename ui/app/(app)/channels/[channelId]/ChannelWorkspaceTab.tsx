import { Spinner } from "@/src/components/shared/Spinner";
import { useMemo, useState } from "react";
import {
  ChevronRight, ExternalLink, FileText, FolderClosed, Plus, X, RefreshCw, FolderSearch, BookOpen,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, EmptyState, TextInput, FormRow, SelectInput,
} from "@/src/components/shared/FormControls";
import { ActionButton, AdvancedSection } from "@/src/components/shared/SettingsControls";
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
  if (relative === "/") {
    return [{ label: KB_FOLDER_NAME, path: rootPath }];
  }
  const parts = relative.split("/").filter(Boolean);
  const crumbs = [{ label: KB_FOLDER_NAME, path: rootPath }];
  let current = stripLeadingSlash(rootPath);
  for (const part of parts) {
    current = `${current}/${part}`;
    crumbs.push({ label: part, path: ensureLeadingSlash(current) });
  }
  return crumbs;
}


// ---------------------------------------------------------------------------
// File content viewer
// ---------------------------------------------------------------------------
function FileViewer({ workspaceId, path }: { workspaceId: string; path: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useWorkspaceFileContent(workspaceId, path);

  if (isLoading) return <div style={{ padding: 16, display: "flex", flexDirection: "row", justifyContent: "center" }}><Spinner color={t.accent} /></div>;
  if (!data) return <span style={{ color: t.textDim, padding: 16, fontSize: 12 }}>File not found</span>;

  return (
    <div style={{
      backgroundColor: t.surfaceOverlay,
      borderRadius: 6,
      padding: 12,
      maxHeight: 400,
      overflow: "scroll" as any,
    }}>
      <span style={{ color: t.textDim, fontSize: 11, marginBottom: 8, fontWeight: "600" }}>
        {path}
      </span>
      <pre style={{ color: t.text, fontSize: 12, fontFamily: "monospace", margin: 0, whiteSpace: "pre-wrap" }}>
        {data.content}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knowledge Base — convention-based auto-indexed folder (primary surface)
// ---------------------------------------------------------------------------
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
  const t = useThemeTokens();
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
  const guideRows = [
    {
      label: "Channel knowledge",
      body: "Files in this folder are auto-indexed and relevant excerpts are auto-retrieved into channel turns. The model sees only matching chunks, not the whole folder.",
    },
    {
      label: "Bot knowledge",
      body: botKnowledgeAutoRetrieval === false
        ? "Bot-wide reference docs live in the bot's own `knowledge-base/` folder and travel across channels. This bot is currently in search-only mode, so those files stay available through `search_bot_knowledge` but are not auto-retrieved."
        : "Bot-wide reference docs live in the bot's own `knowledge-base/` folder and travel across channels. Matching excerpts are auto-retrieved before broad workspace search, and deeper follow-ups should use `search_bot_knowledge`.",
    },
    {
      label: "Use these tools",
      body: "`search_channel_knowledge` is the narrow lookup for this folder. `search_bot_knowledge` is for facts that should follow the bot everywhere. `search_channel_workspace` is broader and better for 'where did we put X?' questions.",
    },
    {
      label: "What belongs here",
      body: "Put stable reference material here: decisions, runbooks, specs, glossaries, operating notes, and curated lists the bot may need again. Subfolders are organizational only; indexing is recursive.",
    },
    {
      label: "What belongs elsewhere",
      body: "Keep short behavioral notes in `memory.md`. Keep transient notes, working files, and one-off outputs in the normal workspace/files surface.",
    },
  ] as const;
  const openWorkspaceButton = workspaceId ? (
    <Link
      to={`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(rootPath)}`}
      style={{
        display: "inline-flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        minHeight: 36,
        paddingLeft: 12,
        paddingRight: 12,
        borderRadius: 7,
        border: `1px solid ${t.surfaceBorder}`,
        backgroundColor: t.surfaceOverlay,
        color: t.text,
        fontSize: 12,
        fontWeight: 600,
        textDecoration: "none",
      }}
    >
      <ExternalLink size={13} color={t.accent} />
      Open KB In Workspace
    </Link>
  ) : null;
  const botKnowledgePath = botId
    ? (sharedWorkspaceId ? `bots/${botId}/${KB_FOLDER_NAME}/` : `${KB_FOLDER_NAME}/`)
    : null;

  return (
    <Section
      title="Knowledge Base"
      description={
        "This channel's `knowledge-base/` is the durable reference layer for room-specific facts. It is auto-indexed, channel-scoped, and used by semantic retrieval plus the narrow knowledge search tools."
      }
      action={openWorkspaceButton}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            padding: 12,
            borderRadius: 8,
            backgroundColor: t.surfaceOverlay,
          }}
        >
          <BookOpen size={18} color={t.accent} />
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ color: t.text, fontSize: 13, fontWeight: "600", fontFamily: "monospace" }}>
              channels/{channelId}/{KB_FOLDER_NAME}/
            </span>
            <span style={{ color: t.textDim, fontSize: 11 }}>
              Indexed recursively. Relevant excerpts are pulled into channel context automatically; deeper lookups use `search_channel_knowledge`.
            </span>
          </div>
        </div>

        {botId && botKnowledgePath ? (
          <div
            style={{
              display: "flex",
              flexDirection: "row",
              gap: 12,
              alignItems: "center",
              padding: "10px 12px",
              borderRadius: 8,
              backgroundColor: t.surfaceOverlay,
              border: `1px solid ${t.surfaceBorder}`,
              flexWrap: "wrap",
            }}
          >
            <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ color: t.text, fontSize: 12, fontWeight: 600 }}>
                Bot knowledge layer
              </span>
              <span style={{ color: t.textDim, fontSize: 11 }}>
                <span style={{ fontFamily: "monospace", color: t.textMuted }}>{botKnowledgePath}</span>
                {" "}· {botKnowledgeAutoRetrieval === false ? "Search only" : "Auto-retrieved + searchable"}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              <Link
                to={`/admin/bots/${botId}`}
                style={{
                  display: "inline-flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  minHeight: 32,
                  paddingLeft: 10,
                  paddingRight: 10,
                  borderRadius: 7,
                  border: `1px solid ${t.surfaceBorder}`,
                  backgroundColor: t.surfaceRaised,
                  color: t.text,
                  fontSize: 12,
                  fontWeight: 600,
                  textDecoration: "none",
                }}
              >
                <ExternalLink size={12} color={t.accent} />
                Bot Workspace
              </Link>
              {workspaceId ? (
                <Link
                  to={`/admin/workspaces/${workspaceId}/files?path=${encodeURIComponent(`/${botKnowledgePath.replace(/\/$/, "")}`)}`}
                  style={{
                    display: "inline-flex",
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    minHeight: 32,
                    paddingLeft: 10,
                    paddingRight: 10,
                    borderRadius: 7,
                    border: `1px solid ${t.surfaceBorder}`,
                    backgroundColor: t.surfaceRaised,
                    color: t.text,
                    fontSize: 12,
                    fontWeight: 600,
                    textDecoration: "none",
                  }}
                >
                  <ExternalLink size={12} color={t.accent} />
                  Open Bot KB
                </Link>
              ) : null}
            </div>
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            borderRadius: 7,
            overflow: "hidden",
            backgroundColor: t.surfaceOverlay,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          {guideRows.map((row, index) => (
            <div
              key={row.label}
              style={{
                padding: "10px 12px",
                display: "flex",
                flexDirection: "row",
                gap: 12,
                alignItems: "flex-start",
                borderTop: index === 0 ? "none" : `1px solid ${t.surfaceBorder}`,
              }}
            >
              <span style={{ color: t.textMuted, fontSize: 11, fontWeight: 600, width: 120, flexShrink: 0 }}>
                {row.label}
              </span>
              <span style={{ color: t.textDim, fontSize: 12, lineHeight: 1.5, maxWidth: 760 }}>
                {row.body}
              </span>
            </div>
          ))}
        </div>

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            padding: 12,
            borderRadius: 8,
            backgroundColor: t.surfaceOverlay,
          }}
        >
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div style={{ minWidth: 0 }}>
              <span style={{ color: t.text, fontSize: 13, fontWeight: 600, display: "block" }}>
                Contents
              </span>
              <span style={{ color: t.textDim, fontSize: 11 }}>
                {folderCount} folder{folderCount === 1 ? "" : "s"} · {fileCount} file{fileCount === 1 ? "" : "s"} in {breadcrumbs[breadcrumbs.length - 1]?.label ?? KB_FOLDER_NAME}
              </span>
            </div>
            {workspaceId ? (
              <ActionButton
                label="Refresh"
                variant="secondary"
                size="small"
                onPress={() => { void refetch(); }}
                icon={<RefreshCw size={13} />}
              />
            ) : null}
          </div>

          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {breadcrumbs.map((crumb, index) => {
              const isActive = index === breadcrumbs.length - 1;
              return (
                <div key={crumb.path} style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <button
                    type="button"
                    onClick={() => {
                      setCurrentPath(crumb.path);
                      onSelectPath(null);
                    }}
                    disabled={isActive}
                    style={{
                      border: "none",
                      background: "transparent",
                      padding: 0,
                      color: isActive ? t.text : t.textDim,
                      fontSize: 12,
                      fontWeight: isActive ? 600 : 500,
                      cursor: isActive ? "default" : "pointer",
                    }}
                  >
                    {crumb.label}
                  </button>
                  {index < breadcrumbs.length - 1 ? <ChevronRight size={12} color={t.textDim} /> : null}
                </div>
              );
            })}
          </div>

          {parentPath ? (
            <button
              type="button"
              onClick={() => {
                setCurrentPath(parentPath);
                onSelectPath(null);
              }}
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                border: "none",
                background: "transparent",
                padding: 0,
                color: t.textDim,
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              <ChevronRight size={12} color={t.textDim} style={{ transform: "rotate(180deg)" }} />
              Up one level
            </button>
          ) : null}

          {!workspaceId ? (
            <EmptyState message="This channel does not currently have a workspace attached, so the knowledge base contents cannot be browsed here." />
          ) : isLoading ? (
            <div style={{ padding: 24, display: "flex", justifyContent: "center" }}>
              <Spinner color={t.accent} />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState message="No knowledge-base files yet. Drop reference docs here and they will start indexing automatically." />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {entries.map((entry: WorkspaceFileEntry) => {
                const fullPath = ensureLeadingSlash(entry.path);
                const isSelected = !entry.is_dir && selectedPath === fullPath;
                const metaLabel = entry.is_dir
                  ? `${relativeToRoot(entry.path, rootPath)}`
                  : `${relativeToRoot(entry.path, rootPath)} · ${formatBytes(entry.size)}`;
                return (
                  <button
                    key={fullPath}
                    type="button"
                    onClick={() => {
                      if (entry.is_dir) {
                        setCurrentPath(fullPath);
                        onSelectPath(null);
                      } else {
                        onSelectPath(fullPath);
                      }
                    }}
                    style={{
                      display: "flex",
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 10,
                      width: "100%",
                      textAlign: "left",
                      padding: "10px 12px",
                      borderRadius: 7,
                      border: `1px solid ${isSelected ? t.accentBorder : "transparent"}`,
                      backgroundColor: isSelected ? t.accentSubtle : t.surfaceRaised,
                      cursor: "pointer",
                    }}
                  >
                    {entry.is_dir ? (
                      <FolderClosed size={16} color={t.accent} />
                    ) : (
                      <FileText size={16} color={t.textDim} />
                    )}
                    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                      <span style={{ color: t.text, fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {entry.display_name || entry.name}
                      </span>
                      <span style={{ color: t.textDim, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {metaLabel}
                      </span>
                    </div>
                    <span style={{ color: t.textMuted, fontSize: 11, flexShrink: 0 }}>
                      {entry.is_dir ? "Open" : formatBytes(entry.size)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Helper: display value with inherited default
// ---------------------------------------------------------------------------
function DefaultHint({ value, defaultValue, label }: { value: string | undefined | null; defaultValue: string; label?: string }) {
  const t = useThemeTokens();
  if (value) return null;
  return (
    <span style={{ color: t.textDim, fontSize: 10, fontStyle: "italic" }}>
      {label ? `${label}: ` : ""}{defaultValue}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Indexed Directories section
// ---------------------------------------------------------------------------
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
  const t = useThemeTokens();
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
    if (newPatterns.trim()) {
      seg.patterns = newPatterns.split(",").map((p) => p.trim()).filter(Boolean);
    }
    if (newModel.trim()) {
      seg.embedding_model = newModel.trim();
    }
    if (newTopK.trim()) {
      const parsed = parseInt(newTopK.trim(), 10);
      if (!isNaN(parsed) && parsed > 0) seg.top_k = parsed;
    }
    if (newThreshold.trim()) {
      const parsed = parseFloat(newThreshold.trim());
      if (!isNaN(parsed) && parsed >= 0 && parsed <= 1) seg.similarity_threshold = parsed;
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
        <div style={{ display: "flex", flexDirection: "row", gap: 6 }}>
          <button type="button"
            onClick={() => reindexMutation.mutate()}
            disabled={reindexMutation.isPending || segments.length === 0}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingLeft: 8, paddingRight: 8,
              paddingTop: 4, paddingBottom: 4,
              borderRadius: 4,
              backgroundColor: t.surfaceOverlay,
              opacity: reindexMutation.isPending || segments.length === 0 ? 0.5 : 1,
            }}
          >
            <RefreshCw size={12} color={t.accent} />
            <span style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>
              {reindexMutation.isPending ? "Reindexing..." : "Reindex"}
            </span>
          </button>
        </div>
      }
    >
      {segments.length === 0 && !adding && (
        <EmptyState message="No indexed directories configured. Add one to enable automatic semantic retrieval from those files." />
      )}

      {segments.map((seg, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingTop: 6, paddingBottom: 6,
            paddingLeft: 10, paddingRight: 10,
            borderRadius: 6,
            backgroundColor: t.surfaceOverlay,
            marginBottom: 4,
          }}
        >
          <FolderSearch size={14} color={t.accent} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ color: t.text, fontSize: 13, fontFamily: "monospace", fontWeight: "500" }}>
              {seg.path_prefix}
            </span>
            <span style={{ color: t.textDim, fontSize: 11 }}>
              patterns: {seg.patterns?.join(", ") || defaultPatterns}
              {" "}&middot;{" "}
              model: {seg.embedding_model || defaultModel}
              {" "}&middot;{" "}
              top_k: {seg.top_k ?? defaultTopK}
              {" "}&middot;{" "}
              threshold: {seg.similarity_threshold ?? defaultThreshold}
            </span>
          </div>
          <button type="button" onClick={() => handleRemove(i)} style={{ padding: 4 }}>
            <X size={13} color={t.danger} />
          </button>
        </div>
      ))}

      {adding ? (
        <div style={{
          display: "flex",
          gap: 8,
          padding: 10,
          borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
        }}>
          <FormRow label="Path prefix" description="Relative to channel workspace, e.g. data/repo">
            <TextInput
              value={newPath}
              onChangeText={setNewPath}
              placeholder="data/repo"
            />
          </FormRow>
          <FormRow label="Patterns (optional)" description="Comma-separated globs. Prefix with ! to exclude (e.g. !**/test/**)">
            <TextInput
              value={newPatterns}
              onChangeText={setNewPatterns}
              placeholder={defaultPatterns}
            />
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
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <div style={{ flex: 1 }}>
              <FormRow label="Top K (optional)" description="Max results returned">
                <TextInput
                  value={newTopK}
                  onChangeText={setNewTopK}
                  placeholder={String(defaultTopK)}
                />
                <DefaultHint value={newTopK} defaultValue={String(defaultTopK)} label="Inherited" />
              </FormRow>
            </div>
            <div style={{ flex: 1 }}>
              <FormRow label="Similarity threshold (optional)" description="Min cosine similarity (0-1)">
                <TextInput
                  value={newThreshold}
                  onChangeText={setNewThreshold}
                  placeholder={String(defaultThreshold)}
                />
                <DefaultHint value={newThreshold} defaultValue={String(defaultThreshold)} label="Inherited" />
              </FormRow>
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button type="button"
              onClick={handleAdd}
              disabled={!newPath.trim()}
              style={{
                paddingLeft: 12, paddingRight: 12,
                paddingTop: 6, paddingBottom: 6,
                borderRadius: 6,
                backgroundColor: t.accent,
                opacity: newPath.trim() ? 1 : 0.5,
              }}
            >
              <span style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>Add</span>
            </button>
            <button type="button"
              onClick={() => { setAdding(false); setNewPath(""); setNewPatterns(""); setNewModel(""); setNewTopK(""); setNewThreshold(""); }}
              style={{ paddingLeft: 12, paddingRight: 12, paddingTop: 6, paddingBottom: 6, borderRadius: 6 }}
            >
              <span style={{ color: t.textMuted, fontSize: 12 }}>Cancel</span>
            </button>
          </div>
        </div>
      ) : (
        <button type="button"
          onClick={() => setAdding(true)}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingTop: 8, paddingBottom: 8,
            paddingLeft: 10, paddingRight: 10,
          }}
        >
          <Plus size={14} color={t.accent} />
          <span style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Add Directory</span>
        </button>
      )}

      {defaults && segments.length === 0 && !adding && (
        <div style={{ marginTop: 4, paddingLeft: 4, paddingRight: 4 }}>
          <span style={{ color: t.textDim, fontSize: 10, lineHeight: 16 }}>
            Defaults from bot workspace config: top_k={defaultTopK}, threshold={defaultThreshold}, model={defaultModel}
          </span>
        </div>
      )}

      {reindexMutation.isSuccess && (
        <span style={{ color: t.success, fontSize: 11, marginTop: 4 }}>
          Reindex complete
        </span>
      )}
      {reindexMutation.isError && (
        <span style={{ color: t.danger, fontSize: 11, marginTop: 4 }}>
          Reindex failed: {(reindexMutation.error as Error)?.message || "Unknown error"}
        </span>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------
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
          description="Optional template defining how workspace files should be structured. Integrations with capabilities (e.g. Mission Control) teach file organization automatically."
        >
          <WorkspaceSchemaEditor
            templateId={form.workspace_schema_template_id ?? null}
            schemaContent={form.workspace_schema_content ?? null}
            onTemplateChange={(id) => {
              patch("workspace_schema_template_id", id);
            }}
            onContentChange={(content) => {
              patch("workspace_schema_content", content);
            }}
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
            <FormRow label="Workspace base prompt" description="common/prompts/base.md from the workspace replaces the global base prompt. Per-bot additions concatenated after.">
              <SelectInput
                value={form.workspace_base_prompt_enabled === null || form.workspace_base_prompt_enabled === undefined ? "inherit" : form.workspace_base_prompt_enabled ? "on" : "off"}
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
