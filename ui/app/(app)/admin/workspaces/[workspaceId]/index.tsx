import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useCallback, useEffect, useMemo, useRef } from "react";

import { useParams } from "react-router-dom";
import { Trash2, AlertCircle } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  useWorkspace, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
} from "@/src/api/hooks/useWorkspaces";
import type { SharedWorkspace } from "@/src/types/api";
import {
  FormRow, TextInput, Section, TabBar,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

// Tab components
import { BotsTab } from "./BotsTab";
import { PromptsTab } from "./PromptsTab";
import { FilesTab } from "./FilesTab";
import { IndexingTab } from "./IndexingTab";
import { EnvEditor } from "./DockerTab";

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "bots", label: "Bots" },
  { key: "prompts", label: "Prompts" },
  { key: "files", label: "Files" },
  { key: "indexing", label: "Indexing" },
];

const NEW_TABS = [
  { key: "overview", label: "Overview" },
  { key: "prompts", label: "Prompts" },
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function WorkspaceDetailScreen() {
  const t = useThemeTokens();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const isNew = workspaceId === "new";
  const goBack = useGoBack("/admin/workspaces");
  const { data: workspace, isLoading } = useWorkspace(isNew ? undefined : workspaceId);
  const createMut = useCreateWorkspace();
  const updateMut = useUpdateWorkspace(workspaceId!);
  const deleteMut = useDeleteWorkspace();

  const { width } = useWindowSize();
  const isWide = width >= 768;

  const [activeTab, setActiveTab] = useState("overview");

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [env, setEnv] = useState<{ key: string; value: string }[]>([]);
  const [basePromptEnabled, setBasePromptEnabled] = useState(true);
  const [writeProtectedPaths, setWriteProtectedPaths] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(isNew);

  if (workspace && !initialized) {
    setName(workspace.name || "");
    setDescription(workspace.description || "");
    setEnv(Object.entries(workspace.env || {}).map(([k, v]) => ({ key: k, value: v as string })));
    setBasePromptEnabled(workspace.workspace_base_prompt_enabled ?? true);
    setWriteProtectedPaths(workspace.write_protected_paths || []);
    setInitialized(true);
  }

  const handleSave = useCallback(async () => {
    const envDict = Object.fromEntries(env.filter((e) => e.key).map((e) => [e.key, e.value]));
    if (isNew) {
      if (!name.trim()) return;
      await createMut.mutateAsync({
        name: name.trim(),
        description: description || undefined,
        env: Object.keys(envDict).length ? envDict : undefined,
        workspace_base_prompt_enabled: basePromptEnabled,
        write_protected_paths: writeProtectedPaths,
      });
      goBack();
    } else {
      await updateMut.mutateAsync({
        name: name.trim() || undefined,
        description,
        env: envDict,
        workspace_base_prompt_enabled: basePromptEnabled,
        write_protected_paths: writeProtectedPaths,
      });
      savedSnapshot.current = currentSnapshot;
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2000);
    }
  }, [isNew, name, description, env, basePromptEnabled, writeProtectedPaths, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!workspaceId || !confirm("Delete this workspace? All workspace data will be removed.")) return;
    await deleteMut.mutateAsync(workspaceId);
    goBack();
  }, [workspaceId, deleteMut, goBack]);

  // -- Dirty tracking --
  const savedSnapshot = useRef<string>("");
  const currentSnapshot = useMemo(() =>
    JSON.stringify({ name, description, env, basePromptEnabled, writeProtectedPaths }),
    [name, description, env, basePromptEnabled, writeProtectedPaths],
  );
  useEffect(() => {
    if (initialized && !savedSnapshot.current) {
      savedSnapshot.current = currentSnapshot;
    }
  }, [initialized, currentSnapshot]);

  const isDirty = isNew || (initialized && currentSnapshot !== savedSnapshot.current);

  const [justSaved, setJustSaved] = useState(false);

  // -- Validation warnings --
  const hasEmptyEnvKeys = env.some((e) => !e.key);
  const hasWarnings = hasEmptyEnvKeys;

  // -- Warn on navigate away with unsaved changes --
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = !!name.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const activeTabs = isNew ? NEW_TABS : TABS;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Workspaces"
        backTo="/admin/workspaces"
        title={isNew ? "New Workspace" : "Edit Workspace"}
        subtitle={!isNew ? workspaceId?.slice(0, 8) : undefined}
        right={
          <>
            {!isNew && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                title="Delete"
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: isWide ? 6 : 0,
                  padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
                  border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                  background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
                }}
              >
                <Trash2 size={14} />
                {isWide && "Delete"}
              </button>
            )}
            {isDirty && !isNew && !justSaved && (
              <span style={{
                fontSize: 11, fontWeight: 600, color: t.warningMuted,
                flexShrink: 0, whiteSpace: "nowrap",
              }}>
                Unsaved changes
              </span>
            )}
            {justSaved && (
              <span style={{
                fontSize: 11, fontWeight: 600, color: t.success,
                flexShrink: 0,
              }}>
                Saved
              </span>
            )}
          </>
        }
      />

      <div className="flex-1 overflow-y-auto" style={{ padding: 24 }}>
        <TabBar tabs={activeTabs} active={activeTab} onChange={setActiveTab} />

        {/* Validation warnings */}
        {hasWarnings && (
          <div style={{
            marginTop: 12, padding: "8px 12px", borderRadius: 6,
            background: t.warningSubtle, color: t.warning, fontSize: 12,
            display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
          }}>
            <AlertCircle size={14} />
            <span>
              {hasEmptyEnvKeys && "Some env variables have empty keys. "}
            </span>
          </div>
        )}

        {/* Error display */}
        {mutError && (
          <div style={{
            marginTop: 12, padding: "8px 12px", borderRadius: 6,
            background: t.dangerSubtle, color: t.danger, fontSize: 12,
          }}>
            {(mutError as any)?.message || String(mutError)}
          </div>
        )}

        {/* Save button */}
        <div style={{ marginTop: 16, marginBottom: 24 }}>
          <button
            onClick={handleSave}
            disabled={!canSave || isSaving || (!isDirty && !isNew)}
            style={{
              padding: "8px 20px", fontSize: 13, fontWeight: 600,
              borderRadius: 6, border: "none", cursor: "pointer",
              background: canSave && isDirty ? t.accent : t.surfaceOverlay,
              color: canSave && isDirty ? "#fff" : t.textDim,
              opacity: isSaving ? 0.6 : 1,
            }}
          >
            {isSaving ? "Saving..." : isNew ? "Create Workspace" : "Save Changes"}
          </button>
        </div>

        {/* ---- Overview Tab ---- */}
        {activeTab === "overview" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            <Section title="Identity">
              <FormRow label="Name" description="Unique workspace name">
                <TextInput value={name} onChangeText={setName} placeholder="e.g. my-workspace" />
              </FormRow>
              <FormRow label="Description">
                <TextInput value={description} onChangeText={setDescription} placeholder="Optional description" />
              </FormRow>
            </Section>

            {/* Environment Variables */}
            <Section title="Environment Variables">
              <EnvEditor entries={env} onChange={setEnv} />
            </Section>

            {/* Info (existing workspace) */}
            {!isNew && workspace && (
              <Section title="Info">
                <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 11 }}>
                  <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>ID</span>
                    <span style={{ color: t.text, fontFamily: "monospace" }}>{workspace.id}</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>Created</span>
                    <span style={{ color: t.textMuted }}>
                      {new Date(workspace.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                    </span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between" }}>
                    <span style={{ color: t.textDim }}>Updated</span>
                    <span style={{ color: t.textMuted }}>
                      {new Date(workspace.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                    </span>
                  </div>
                </div>
              </Section>
            )}
          </div>
        )}

        {/* ---- Bots Tab ---- */}
        {activeTab === "bots" && !isNew && workspace && (
          <BotsTab
            workspaceId={workspaceId!}
            bots={workspace.bots}
            writeProtectedPaths={workspace.write_protected_paths || []}
          />
        )}

        {/* ---- Prompts Tab ---- */}
        {activeTab === "prompts" && (
          <PromptsTab
            workspaceId={workspaceId!}
            isNew={isNew}
            basePromptEnabled={basePromptEnabled}
            setBasePromptEnabled={setBasePromptEnabled}
          />
        )}

        {/* ---- Files Tab ---- */}
        {activeTab === "files" && !isNew && (
          <FilesTab
            workspaceId={workspaceId!}
            currentStatus="running"
          />
        )}

        {/* ---- Indexing Tab ---- */}
        {activeTab === "indexing" && !isNew && (
          <IndexingTab
            workspaceId={workspaceId!}
            writeProtectedPaths={writeProtectedPaths}
            setWriteProtectedPaths={setWriteProtectedPaths}
          />
        )}
      </div>
    </div>
  );
}
