import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import {
  FileText, Archive, Trash2, ChevronDown, ChevronRight,
  ExternalLink, Code, Database, Plus, X, RefreshCw, FolderSearch, RotateCw,
} from "lucide-react";
import { Link } from "expo-router";
import { useMutation } from "@tanstack/react-query";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, Toggle, EmptyState, TextInput, FormRow, SelectInput,
} from "@/src/components/shared/FormControls";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import { WorkspaceSchemaEditor } from "@/src/components/shared/WorkspaceSchemaEditor";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  useChannelWorkspaceFiles,
  useChannelWorkspaceFileContent,
  useDeleteChannelWorkspaceFile,
  useActivatableIntegrations,
} from "@/src/api/hooks/useChannels";
import { InfoBanner } from "@/src/components/shared/SettingsControls";
import { useEnableEditor } from "@/src/api/hooks/useWorkspaces";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { useFileBrowserStore } from "@/src/stores/fileBrowser";
import { apiFetch } from "@/src/api/client";
import type { ChannelSettings } from "@/src/types/api";

type IndexSegment = NonNullable<ChannelSettings["index_segments"]>[number];
type SegmentDefaults = NonNullable<ChannelSettings["index_segment_defaults"]>;

// ---------------------------------------------------------------------------
// File list item
// ---------------------------------------------------------------------------
function FileItem({
  file,
  channelId,
  onSelect,
  selected,
}: {
  file: { name: string; path: string; size: number; modified_at: number; section: string };
  channelId: string;
  onSelect: (path: string) => void;
  selected: boolean;
}) {
  const t = useThemeTokens();
  const deleteMutation = useDeleteChannelWorkspaceFile(channelId);
  const modified = new Date(file.modified_at * 1000);
  const sizeKb = (file.size / 1024).toFixed(1);

  const icon =
    file.section === "archive" ? <Archive size={14} color={t.textMuted} /> :
    file.section === "data" ? <Database size={14} color={t.textMuted} /> :
    <FileText size={14} color={t.accent} />;

  return (
    <Pressable
      onPress={() => onSelect(file.path)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingVertical: 8,
        paddingHorizontal: 12,
        borderRadius: 6,
        backgroundColor: selected ? t.surfaceOverlay : "transparent",
      }}
    >
      {icon}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={{ color: t.text, fontSize: 13, fontWeight: "500" }} numberOfLines={1}>
          {file.name}
        </Text>
        <Text style={{ color: t.textDim, fontSize: 11 }}>
          {sizeKb} KB &middot; {modified.toLocaleDateString()}
        </Text>
      </View>
      <Pressable
        onPress={(e) => {
          e.stopPropagation();
          if (confirm(`Delete ${file.name}?`)) {
            deleteMutation.mutate(file.path);
          }
        }}
        style={{ padding: 4 }}
      >
        <Trash2 size={13} color={t.danger} />
      </Pressable>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// File content viewer
// ---------------------------------------------------------------------------
function FileViewer({ channelId, path }: { channelId: string; path: string }) {
  const t = useThemeTokens();
  const { data, isLoading } = useChannelWorkspaceFileContent(channelId, path);

  if (isLoading) return <ActivityIndicator color={t.accent} style={{ padding: 16 }} />;
  if (!data) return <Text style={{ color: t.textDim, padding: 16, fontSize: 12 }}>File not found</Text>;

  return (
    <View style={{
      backgroundColor: t.surfaceOverlay,
      borderRadius: 6,
      padding: 12,
      maxHeight: 400,
      overflow: "scroll" as any,
    }}>
      <Text style={{ color: t.textDim, fontSize: 11, marginBottom: 8, fontWeight: "600" }}>
        {path}
      </Text>
      <pre style={{ color: t.text, fontSize: 12, fontFamily: "monospace", margin: 0, whiteSpace: "pre-wrap" }}>
        {data.content}
      </pre>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Workspace links bar
// ---------------------------------------------------------------------------
function WorkspaceLinks({ workspaceId, channelId }: { workspaceId: string; channelId: string }) {
  const t = useThemeTokens();
  const enableEditorMutation = useEnableEditor(workspaceId);
  const [editorOpening, setEditorOpening] = useState(false);
  const expandDir = useFileBrowserStore((s) => s.expandDir);

  const handleBrowse = () => {
    // Expand the tree to the channel workspace folder before navigating
    const segments = ["channels", `channels/${channelId}`, `channels/${channelId}/workspace`];
    for (const seg of segments) {
      expandDir(seg);
    }
  };

  const handleOpenEditor = async () => {
    setEditorOpening(true);
    try {
      await enableEditorMutation.mutateAsync();
      const { serverUrl } = useAuthStore.getState();
      const token = getAuthToken();
      const folder = `/workspace/channels/${channelId}`;
      const editorUrl = `${serverUrl}/api/v1/workspaces/${workspaceId}/editor/?tkn=${encodeURIComponent(token || "")}&folder=${encodeURIComponent(folder)}`;
      window.open(editorUrl, `editor-${workspaceId}`);
    } catch (err) {
      console.error("Failed to open editor:", err);
    } finally {
      setEditorOpening(false);
    }
  };

  return (
    <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
      <Link href={`/admin/workspaces/${workspaceId}/files` as any} asChild>
        <Pressable
          onPress={handleBrowse}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingHorizontal: 12,
            paddingVertical: 8,
            borderRadius: 6,
            borderWidth: 1,
            borderColor: t.surfaceBorder,
            backgroundColor: t.surfaceOverlay,
          }}
        >
          <ExternalLink size={13} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Browse in Workspace</Text>
        </Pressable>
      </Link>
      <Pressable
        onPress={handleOpenEditor}
        disabled={editorOpening || enableEditorMutation.isPending}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          paddingHorizontal: 12,
          paddingVertical: 8,
          borderRadius: 6,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          backgroundColor: t.surfaceOverlay,
          opacity: editorOpening ? 0.5 : 1,
        }}
      >
        <Code size={13} color={t.accent} />
        <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>
          {editorOpening ? "Opening..." : "Open in Editor"}
        </Text>
      </Pressable>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Collapsible file section
// ---------------------------------------------------------------------------
function CollapsibleFileSection({
  title,
  files,
  channelId,
  selectedPath,
  onSelect,
  defaultOpen = false,
}: {
  title: string;
  files: { name: string; path: string; size: number; modified_at: number; section: string }[];
  channelId: string;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  defaultOpen?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);

  if (files.length === 0) return null;

  return (
    <Section
      title={
        <Pressable
          onPress={() => setOpen(!open)}
          style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
        >
          {open ? <ChevronDown size={14} color={t.textMuted} /> : <ChevronRight size={14} color={t.textMuted} />}
          <Text style={{ color: t.text, fontSize: 14, fontWeight: "600" }}>
            {title} ({files.length})
          </Text>
        </Pressable> as any
      }
    >
      {open && (
        <View style={{ gap: 2 }}>
          {files.map((f) => (
            <FileItem
              key={f.path}
              file={f}
              channelId={channelId}
              onSelect={onSelect}
              selected={selectedPath === f.path}
            />
          ))}
        </View>
      )}
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
    <Text style={{ color: t.textDim, fontSize: 10, fontStyle: "italic" }}>
      {label ? `${label}: ` : ""}{defaultValue}
    </Text>
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

  const reindexMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/reindex-segments`, { method: "POST" }),
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
    onChange([...segments, seg]);
    setNewPath("");
    setNewPatterns("");
    setNewModel("");
    setAdding(false);
  };

  const handleRemove = (idx: number) => {
    onChange(segments.filter((_, i) => i !== idx));
  };

  return (
    <Section
      title="Indexed Directories"
      description="Additional folders to index for code search. Paths relative to channel workspace."
      action={
        <View style={{ flexDirection: "row", gap: 6 }}>
          <Pressable
            onPress={() => reindexMutation.mutate()}
            disabled={reindexMutation.isPending || segments.length === 0}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              paddingHorizontal: 8,
              paddingVertical: 4,
              borderRadius: 4,
              backgroundColor: t.surfaceOverlay,
              opacity: reindexMutation.isPending || segments.length === 0 ? 0.5 : 1,
            }}
          >
            <RefreshCw size={12} color={t.accent} />
            <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>
              {reindexMutation.isPending ? "Reindexing..." : "Reindex"}
            </Text>
          </Pressable>
        </View>
      }
    >
      {segments.length === 0 && !adding && (
        <EmptyState message="No indexed directories configured. Add one to enable code search." />
      )}

      {segments.map((seg, i) => (
        <View
          key={i}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingVertical: 6,
            paddingHorizontal: 10,
            borderRadius: 6,
            backgroundColor: t.surfaceOverlay,
            marginBottom: 4,
          }}
        >
          <FolderSearch size={14} color={t.accent} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ color: t.text, fontSize: 13, fontFamily: "monospace", fontWeight: "500" }} numberOfLines={1}>
              {seg.path_prefix}
            </Text>
            <Text style={{ color: t.textDim, fontSize: 11 }}>
              patterns: {seg.patterns?.join(", ") || defaultPatterns}
              {" "}&middot;{" "}
              model: {seg.embedding_model || defaultModel}
            </Text>
          </View>
          <Pressable onPress={() => handleRemove(i)} style={{ padding: 4 }}>
            <X size={13} color={t.danger} />
          </Pressable>
        </View>
      ))}

      {adding ? (
        <View style={{
          gap: 8,
          padding: 10,
          borderRadius: 6,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
        }}>
          <FormRow label="Path prefix" description="Relative to channel workspace, e.g. data/repo">
            <TextInput
              value={newPath}
              onChangeText={setNewPath}
              placeholder="data/repo"
            />
          </FormRow>
          <FormRow label="Patterns (optional)" description="Comma-separated globs">
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
          <View style={{ flexDirection: "row", gap: 8 }}>
            <Pressable
              onPress={handleAdd}
              disabled={!newPath.trim()}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 6,
                backgroundColor: t.accent,
                opacity: newPath.trim() ? 1 : 0.5,
              }}
            >
              <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>Add</Text>
            </Pressable>
            <Pressable
              onPress={() => { setAdding(false); setNewPath(""); setNewPatterns(""); setNewModel(""); }}
              style={{ paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6 }}
            >
              <Text style={{ color: t.textMuted, fontSize: 12 }}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable
          onPress={() => setAdding(true)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 6,
            paddingVertical: 8,
            paddingHorizontal: 10,
          }}
        >
          <Plus size={14} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 12, fontWeight: "600" }}>Add Directory</Text>
        </Pressable>
      )}

      {defaults && segments.length === 0 && !adding && (
        <View style={{ marginTop: 4, paddingHorizontal: 4 }}>
          <Text style={{ color: t.textDim, fontSize: 10, lineHeight: 16 }}>
            Defaults from bot workspace config: top_k={defaultTopK}, threshold={defaultThreshold}, model={defaultModel}
          </Text>
        </View>
      )}

      {reindexMutation.isSuccess && (
        <Text style={{ color: t.success, fontSize: 11, marginTop: 4 }}>
          Reindex complete
        </Text>
      )}
      {reindexMutation.isError && (
        <Text style={{ color: t.danger, fontSize: 11, marginTop: 4 }}>
          Reindex failed: {(reindexMutation.error as Error)?.message || "Unknown error"}
        </Text>
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

  // Detect any active integration that declares template compatibility
  const { data: activatable } = useActivatableIntegrations(channelId);
  const activeWithTemplates = (activatable ?? []).filter(
    (ig) => ig.activated && ig.compatible_template_tag,
  );
  const highlightTag = activeWithTemplates[0]?.compatible_template_tag ?? undefined;
  const activeIntName = activeWithTemplates[0]
    ? activeWithTemplates[0].integration_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    : "";
  const hasNoSchema = !form.workspace_schema_template_id && !form.workspace_schema_content;

  const { data: filesData, isLoading } = useChannelWorkspaceFiles(
    enabled ? channelId : undefined,
    { includeArchive: true, includeData: true },
  );

  const activeFiles = filesData?.files?.filter((f) => f.section === "active") ?? [];
  const archivedFiles = filesData?.files?.filter((f) => f.section === "archive") ?? [];
  const dataFiles = filesData?.files?.filter((f) => f.section === "data") ?? [];

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
          <Section
            title="Workspace Schema"
            description="Choose an organization template that defines how workspace files should be structured for this type of project."
          >
            {activeWithTemplates.length > 0 && hasNoSchema && (
              <InfoBanner variant="info">
                {activeIntName} is active on this channel. Pick a compatible workspace schema for best results.
              </InfoBanner>
            )}
            <WorkspaceSchemaEditor
              templateId={form.workspace_schema_template_id ?? null}
              schemaContent={form.workspace_schema_content ?? null}
              onTemplateChange={(id) => {
                patch("workspace_schema_template_id", id);
              }}
              onContentChange={(content) => {
                patch("workspace_schema_content", content);
              }}
              highlightTag={highlightTag}
              activeIntegrationName={activeIntName || undefined}
            />
          </Section>

          {workspaceId && (
            <Section title="Workspace Access" description="Open the channel workspace folder in the file browser or VS Code editor.">
              <WorkspaceLinks workspaceId={workspaceId} channelId={channelId} />
            </Section>
          )}

          <Section title="Active Files" description="Markdown files in the channel workspace root. Injected into context automatically.">
            {isLoading ? (
              <ActivityIndicator color={t.accent} style={{ padding: 16 }} />
            ) : activeFiles.length === 0 ? (
              <EmptyState message="No workspace files yet. The bot will create them via exec_command." />
            ) : (
              <View style={{ gap: 2 }}>
                {activeFiles.map((f) => (
                  <FileItem
                    key={f.path}
                    file={f}
                    channelId={channelId}
                    onSelect={setSelectedPath}
                    selected={selectedPath === f.path}
                  />
                ))}
              </View>
            )}
          </Section>

          <CollapsibleFileSection
            title="Archived Files"
            files={archivedFiles}
            channelId={channelId}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
          />

          <CollapsibleFileSection
            title="Data Files"
            files={dataFiles}
            channelId={channelId}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
          />

          {selectedPath && (
            <Section title="File Content">
              <FileViewer channelId={channelId} path={selectedPath} />
            </Section>
          )}

          <AdvancedSection>
            <IndexedDirectoriesSection
              segments={form.index_segments ?? []}
              onChange={(segs) => patch("index_segments", segs)}
              channelId={channelId}
              defaults={indexSegmentDefaults}
            />

            {/* Shared workspace overrides — only when bot has a workspace */}
            {hasSharedWorkspace && (
              <Section title="Shared Workspace Overrides" description="Override workspace-level settings for this channel. These control features inherited from the bot's shared workspace.">
                <FormRow label="Workspace skills" description="Skill .md files from the workspace filesystem, injected into context by mode (pinned/rag/on-demand).">
                  <SelectInput
                    value={form.workspace_skills_enabled === null || form.workspace_skills_enabled === undefined ? "inherit" : form.workspace_skills_enabled ? "on" : "off"}
                    options={[
                      { label: "Inherit from workspace", value: "inherit" },
                      { label: "Enabled", value: "on" },
                      { label: "Disabled", value: "off" },
                    ]}
                    onChange={(v) => patch("workspace_skills_enabled" as any, v === "inherit" ? null : v === "on")}
                  />
                </FormRow>
                {sharedWorkspaceId && (
                  <div style={{ marginTop: 4 }}>
                    <button
                      onClick={async () => {
                        try {
                          const data = await apiFetch<{ embedded?: number; unchanged?: number; errors?: number }>(
                            `/api/v1/workspaces/${sharedWorkspaceId}/reindex-skills`,
                            { method: "POST" },
                          );
                          alert(`Reindexed: ${data.embedded || 0} embedded, ${data.unchanged || 0} unchanged, ${data.errors || 0} errors`);
                        } catch (e) {
                          alert("Failed to reindex skills");
                        }
                      }}
                      style={{
                        display: "flex", alignItems: "center", gap: 4,
                        padding: "5px 12px", fontSize: 11, fontWeight: 600,
                        border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                        background: "transparent", color: t.textMuted, cursor: "pointer",
                      }}
                    >
                      <RotateCw size={11} /> Reindex Skills
                    </button>
                  </div>
                )}
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
