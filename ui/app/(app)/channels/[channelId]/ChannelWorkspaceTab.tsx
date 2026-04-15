import { Spinner } from "@/src/components/shared/Spinner";
import { useState } from "react";
import {
  ExternalLink, Plus, X, RefreshCw, FolderSearch,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, Toggle, EmptyState, TextInput, FormRow, SelectInput,
} from "@/src/components/shared/FormControls";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import { WorkspaceSchemaEditor } from "@/src/components/shared/WorkspaceSchemaEditor";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  useChannelWorkspaceFileContent,
} from "@/src/api/hooks/useChannels";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { apiFetch } from "@/src/api/client";
import { ChannelFileBrowser } from "./ChannelFileBrowser";
import type { ChannelSettings } from "@/src/types/api";

type IndexSegment = NonNullable<ChannelSettings["index_segments"]>[number];
type SegmentDefaults = NonNullable<ChannelSettings["index_segment_defaults"]>;


// ---------------------------------------------------------------------------
// File content viewer
// ---------------------------------------------------------------------------
function FileViewer({ channelId, path }: { channelId: string; path: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useChannelWorkspaceFileContent(channelId, path);

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
// Workspace links bar
// ---------------------------------------------------------------------------
function WorkspaceLinks({ workspaceId, channelId }: { workspaceId: string; channelId: string }) {
  const t = useThemeTokens();
  const expandDir = useFileBrowserStore((s) => s.expandDir);

  const handleBrowse = () => {
    const segments = ["channels", `channels/${channelId}`, `channels/${channelId}/workspace`];
    for (const seg of segments) {
      expandDir(seg);
    }
  };

  return (
    <div style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginBottom: 8}}>
      <Link
        to={`/admin/workspaces/${workspaceId}/files`}
        onClick={handleBrowse}
        style={{
          display: "inline-flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          padding: "8px 12px",
          borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
          backgroundColor: t.surfaceOverlay,
          textDecoration: "none",
        }}
      >
        <ExternalLink size={13} color={t.accent} />
        <span style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Browse in Workspace</span>
      </Link>
    </div>
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
      title="Indexed Directories"
      description="Additional folders to index for semantic search. Contents are automatically retrieved and injected into context when relevant to the conversation."
      action={
        <div style={{ flexDirection: "row", gap: 6 }}>
          <button type="button"
            onClick={() => reindexMutation.mutate()}
            disabled={reindexMutation.isPending || segments.length === 0}
            style={{
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
          <div style={{ flexDirection: "row", gap: 8 }}>
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
          <div style={{ flexDirection: "row", gap: 8 }}>
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
  indexSegmentDefaults,
  hasSharedWorkspace,
  sharedWorkspaceId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  channelId: string;
  workspaceId?: string;
  indexSegmentDefaults?: SegmentDefaults | null;
  hasSharedWorkspace?: boolean;
  sharedWorkspaceId?: string | null;
}) {
  const t = useThemeTokens();
  const enabled = !!form.channel_workspace_enabled;
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  return (
    <>
      {/* Channel workspace — persistent working documents */}
      <Section title="Channel Workspace" description="Persistent working documents for this channel. Auto-injected into every request when enabled.">
        <Toggle
          label="Enable channel workspace"
          value={enabled}
          onChange={(v) => patch("channel_workspace_enabled", v)}
        />
      </Section>

      {enabled && (
        <>
          {workspaceId && (
            <Section title="Workspace Access" description="Open the channel workspace folder in the file browser or VS Code editor.">
              <WorkspaceLinks workspaceId={workspaceId} channelId={channelId} />
            </Section>
          )}

          <ChannelFileBrowser
            channelId={channelId}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
          />

          {selectedPath && (
            <Section title="File Content">
              <FileViewer channelId={channelId} path={selectedPath} />
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

            {/* Shared workspace overrides — only when bot has a workspace */}
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
      )}
    </>
  );
}
