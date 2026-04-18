import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { Trash2, AlertCircle, FolderOpen, ChevronDown, ChevronRight } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  useWorkspace, useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
} from "@/src/api/hooks/useWorkspaces";
import type { SharedWorkspace } from "@/src/types/api";
import {
  FormRow, TextInput, Toggle,
} from "@/src/components/shared/FormControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { useThemeTokens } from "@/src/theme/tokens";

// Section components
import { BotsSection } from "./BotsSection";
import { IndexingSection } from "./IndexingSection";
import { WriteProtection } from "./WriteProtection";

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------
function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="flex flex-col border-t" style={{ borderColor: t.surfaceBorder, paddingTop: 16 }}>
      <button
        onClick={() => setOpen(!open)}
        className="flex flex-row items-center gap-2 w-full text-left bg-transparent border-none cursor-pointer p-0"
      >
        {open
          ? <ChevronDown size={14} color={t.textMuted} className="flex-shrink-0" />
          : <ChevronRight size={14} color={t.textMuted} className="flex-shrink-0" />}
        <span className="text-sm font-semibold flex-1" style={{ color: t.text }}>
          {title}
        </span>
        {subtitle && !open && (
          <span className="text-xs" style={{ color: t.textDim }}>
            {subtitle}
          </span>
        )}
      </button>
      {open && (
        <div className="flex flex-col gap-3 pt-3">
          {children}
        </div>
      )}
    </div>
  );
}

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

  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [basePromptEnabled, setBasePromptEnabled] = useState(true);
  const [writeProtectedPaths, setWriteProtectedPaths] = useState<string[]>([]);
  const [initialized, setInitialized] = useState(isNew);
  const { confirm, ConfirmDialogSlot } = useConfirm();

  if (workspace && !initialized) {
    setName(workspace.name || "");
    setDescription(workspace.description || "");
    setBasePromptEnabled(workspace.workspace_base_prompt_enabled ?? true);
    setWriteProtectedPaths(workspace.write_protected_paths || []);
    setInitialized(true);
  }

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!name.trim()) return;
      await createMut.mutateAsync({
        name: name.trim(),
        description: description || undefined,
        workspace_base_prompt_enabled: basePromptEnabled,
        write_protected_paths: writeProtectedPaths,
      });
      goBack();
    } else {
      await updateMut.mutateAsync({
        name: name.trim() || undefined,
        description,
        workspace_base_prompt_enabled: basePromptEnabled,
        write_protected_paths: writeProtectedPaths,
      });
      savedSnapshot.current = currentSnapshot;
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2000);
    }
  }, [isNew, name, description, basePromptEnabled, writeProtectedPaths, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!workspaceId) return;
    const ok = await confirm(
      "Delete this workspace? All workspace data will be removed.",
      { title: "Delete workspace", confirmLabel: "Delete", variant: "danger" },
    );
    if (!ok) return;
    await deleteMut.mutateAsync(workspaceId);
    goBack();
  }, [workspaceId, deleteMut, goBack, confirm]);

  // -- Dirty tracking --
  const savedSnapshot = useRef<string>("");
  const currentSnapshot = useMemo(() =>
    JSON.stringify({ name, description, basePromptEnabled, writeProtectedPaths }),
    [name, description, basePromptEnabled, writeProtectedPaths],
  );
  useEffect(() => {
    if (initialized && !savedSnapshot.current) {
      savedSnapshot.current = currentSnapshot;
    }
  }, [initialized, currentSnapshot]);

  const isDirty = isNew ? !!name.trim() : (initialized && savedSnapshot.current !== "" && currentSnapshot !== savedSnapshot.current);
  const [justSaved, setJustSaved] = useState(false);

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
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Workspaces"
        backTo="/admin/workspaces"
        title={isNew ? "New Workspace" : "Edit Workspace"}
        subtitle={!isNew ? workspaceId?.slice(0, 8) : undefined}
        right={
          <div className="flex flex-row items-center gap-2">
            {/* File explorer link */}
            {!isNew && (
              <Link
                to={`/admin/workspaces/${workspaceId}/files`}
                title="Browse files"
                className="flex flex-row items-center justify-center"
                style={{
                  width: isWide ? "auto" : 36,
                  height: isWide ? "auto" : 36,
                  padding: isWide ? "6px 14px" : "6px 8px",
                  fontSize: 13,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6,
                  background: "transparent",
                  color: t.textMuted,
                  textDecoration: "none",
                  gap: 6,
                  flexShrink: 0,
                }}
              >
                <FolderOpen size={14} />
                {isWide && <span>Files</span>}
              </Link>
            )}
            {!isNew && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                title="Delete"
                className="flex flex-row items-center"
                style={{
                  gap: isWide ? 6 : 0,
                  padding: isWide ? "6px 14px" : "6px 8px",
                  fontSize: 13,
                  border: `1px solid ${t.dangerBorder}`,
                  borderRadius: 6,
                  background: "transparent",
                  color: t.danger,
                  cursor: "pointer",
                  flexShrink: 0,
                }}
              >
                <Trash2 size={14} />
                {isWide && "Delete"}
              </button>
            )}
            {isDirty && !isNew && !justSaved && (
              <span className="text-xs font-semibold flex-shrink-0 whitespace-nowrap"
                style={{ color: t.warningMuted }}>
                Unsaved changes
              </span>
            )}
            {justSaved && (
              <span className="text-xs font-semibold flex-shrink-0"
                style={{ color: t.success }}>
                Saved
              </span>
            )}
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto p-6">
        {/* Error display */}
        {mutError && (
          <div className="mb-4 px-3 py-2 rounded-md text-xs"
            style={{ background: t.dangerSubtle, color: t.danger }}>
            {(mutError as any)?.message || String(mutError)}
          </div>
        )}

        {/* Save button */}
        <div className="mb-6">
          <button
            onClick={handleSave}
            disabled={!canSave || isSaving || (!isDirty && !isNew)}
            className="px-5 py-2 text-sm font-semibold rounded-md border-none cursor-pointer"
            style={{
              background: canSave && isDirty ? t.accent : t.surfaceOverlay,
              color: canSave && isDirty ? "#fff" : t.textDim,
              opacity: isSaving ? 0.6 : 1,
            }}
          >
            {isSaving ? "Saving..." : isNew ? "Create Workspace" : "Save Changes"}
          </button>
        </div>

        <div className="flex flex-col gap-4">
          {/* ---- Identity (always open) ---- */}
          <div className="flex flex-col gap-4">
            <span className="text-sm font-semibold" style={{ color: t.text }}>Identity</span>
            <FormRow label="Name" description="Unique workspace name">
              <TextInput value={name} onChangeText={setName} placeholder="e.g. my-workspace" />
            </FormRow>
            <FormRow label="Description">
              <TextInput value={description} onChangeText={setDescription} placeholder="Optional description" />
            </FormRow>
            {!isNew && workspace && (
              <div className="flex flex-col gap-1 text-xs mt-2">
                <div className="flex flex-row justify-between">
                  <span style={{ color: t.textDim }}>ID</span>
                  <span className="font-mono" style={{ color: t.text }}>{workspace.id}</span>
                </div>
                <div className="flex flex-row justify-between">
                  <span style={{ color: t.textDim }}>Created</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(workspace.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
                <div className="flex flex-row justify-between">
                  <span style={{ color: t.textDim }}>Updated</span>
                  <span style={{ color: t.textMuted }}>
                    {new Date(workspace.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* ---- Prompts ---- */}
          <CollapsibleSection title="Prompts" subtitle="Base prompt override">
            <FormRow label="Enable workspace base prompt override">
              <Toggle value={basePromptEnabled} onChange={setBasePromptEnabled} />
            </FormRow>
            <div className="text-xs leading-relaxed" style={{ color: t.textMuted }}>
              <div className="font-semibold mb-1" style={{ color: t.textMuted }}>File conventions:</div>
              <div className="flex flex-col gap-0.5">
                <span><code style={{ color: t.accent }}>common/prompts/base.md</code> {"\u2014"} replaces global base prompt for every bot</span>
                <span><code style={{ color: t.warningMuted }}>{"bots/<bot-id>/prompts/base.md"}</code> {"\u2014"} concatenated after common, resolved per bot</span>
              </div>
            </div>
            <div className="text-xs leading-relaxed mt-2" style={{ color: t.textMuted }}>
              <div className="font-semibold mb-1" style={{ color: t.textMuted }}>Persona override:</div>
              <div className="flex flex-col gap-0.5">
                <span><code style={{ color: t.warningMuted }}>{"bots/<bot-id>/persona.md"}</code> {"\u2014"} overrides DB persona (file presence opts in)</span>
              </div>
            </div>
          </CollapsibleSection>

          {/* ---- Bots ---- */}
          {!isNew && workspace && (
            <CollapsibleSection
              title="Bots"
              subtitle={`${workspace.bots.length} enrolled`}
            >
              <BotsSection
                workspaceId={workspaceId!}
                bots={workspace.bots}
                writeProtectedPaths={workspace.write_protected_paths || []}
              />
            </CollapsibleSection>
          )}

          {/* ---- Indexing ---- */}
          {!isNew && (
            <CollapsibleSection title="Indexing">
              <IndexingSection workspaceId={workspaceId!} />
            </CollapsibleSection>
          )}

          {/* ---- Write Protection ---- */}
          {!isNew && (
            <CollapsibleSection
              title="Write Protection"
              subtitle={`${writeProtectedPaths.length} path${writeProtectedPaths.length !== 1 ? "s" : ""}`}
            >
              <WriteProtection paths={writeProtectedPaths} onChange={setWriteProtectedPaths} />
            </CollapsibleSection>
          )}
        </div>
      </div>
      <ConfirmDialogSlot />
    </div>
  );
}
