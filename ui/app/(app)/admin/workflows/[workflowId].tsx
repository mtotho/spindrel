/**
 * Workflow detail page — two-pane layout on desktop, accordion on mobile.
 * Shell: header + tabs + tab content routing.
 */
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useEffect, useCallback, useMemo, useRef } from "react";

import { useParams, useNavigate } from "react-router-dom";
import {
  useWorkflow,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
  useExportWorkflow,
} from "@/src/api/hooks/useWorkflows";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Copy, X as XIcon } from "lucide-react";
import { TabBar } from "@/src/components/shared/FormControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { Workflow, WorkflowStep } from "@/src/types/api";
import WorkflowRunsTab from "./WorkflowRunsTab";
import { WorkflowTemplateGallery } from "./WorkflowTemplateGallery";
import { WorkflowHeader } from "./WorkflowHeader";
import { WorkflowIdentitySection } from "./WorkflowIdentitySection";
import { WorkflowStepList } from "./WorkflowStepList";
import { WorkflowStepDetail, StepDetailEmptyState } from "./WorkflowStepDetail";
import { YamlSyntaxEditor, YamlSyntaxViewer } from "./YamlEditor";
import yaml from "js-yaml";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WorkflowDetailPage() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { width } = useWindowSize();
  const isMobile = width < 768;

  const { workflowId, tab: tabParam, run: runParam, clone: cloneParam } = useParams<{
    workflowId: string;
    tab?: string;
    run?: string;
    clone?: string;
  }>();
  const isNew = workflowId === "new";

  const { data: existing, isLoading } = useWorkflow(isNew ? undefined : workflowId);
  const createMut = useCreateWorkflow();
  const updateMut = useUpdateWorkflow(workflowId || "");
  const deleteMut = useDeleteWorkflow();
  const exportMut = useExportWorkflow(workflowId || "");

  const [activeTab, setActiveTab] = useState<string>(
    !isNew && tabParam === "runs" ? "runs" : "definition"
  );
  const [draft, setDraft] = useState<Partial<Workflow>>({
    id: "", name: "", description: "",
    steps: [], params: {}, defaults: {},
    secrets: [], triggers: {}, tags: [],
    session_mode: "isolated",
  });
  const [dirty, setDirty] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showGallery, setShowGallery] = useState(isNew && !cloneParam);
  const [showYamlImport, setShowYamlImport] = useState(false);
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);

  const isFileBased = existing?.source_type === "file" || existing?.source_type === "integration";

  // Warn on unsaved changes when leaving the page
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Ctrl+S / Cmd+S save shortcut — ref set after handleSave is declared
  const saveRef = useRef<(() => void) | undefined>(undefined);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        saveRef.current?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Hydrate from clone param
  useEffect(() => {
    if (isNew && cloneParam) {
      try {
        const cloneData = JSON.parse(cloneParam);
        setDraft((prev) => ({ ...prev, ...cloneData }));
        setDirty(true);
        setShowGallery(false);
      } catch {
        // ignore bad clone data
      }
    }
  }, [isNew, cloneParam]);

  useEffect(() => {
    if (existing && !isNew) {
      setDraft({
        id: existing.id,
        name: existing.name,
        description: existing.description || "",
        steps: existing.steps || [],
        params: existing.params || {},
        defaults: existing.defaults || {},
        secrets: existing.secrets || [],
        triggers: existing.triggers || {},
        tags: existing.tags || [],
        session_mode: existing.session_mode || "isolated",
      });
    }
  }, [existing, isNew]);

  const update = useCallback((patch: Partial<Workflow>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  }, []);

  const goBack = () => navigate("/admin/workflows");

  const handleClone = () => {
    const cloneData: Partial<Workflow> = {
      id: (draft.id || "workflow") + "-copy",
      name: `${draft.name || "Workflow"} (copy)`,
      description: draft.description || "",
      steps: draft.steps || [],
      params: draft.params || {},
      defaults: draft.defaults || {},
      secrets: draft.secrets || [],
      triggers: draft.triggers || {},
      tags: draft.tags || [],
      session_mode: draft.session_mode || "isolated",
    };
    navigate(`/admin/workflows/new?clone=${encodeURIComponent(JSON.stringify(cloneData))}`);
  };

  const handleSave = async () => {
    try {
      if (isNew) {
        await createMut.mutateAsync({
          id: draft.id || "",
          name: draft.name || "",
          description: draft.description || undefined,
          steps: draft.steps || [],
          params: draft.params || {},
          defaults: draft.defaults || {},
          secrets: draft.secrets || [],
          triggers: draft.triggers || {},
          tags: draft.tags || [],
          session_mode: draft.session_mode || "isolated",
        } as Workflow);
        goBack();
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || undefined,
          steps: draft.steps,
          params: draft.params,
          defaults: draft.defaults,
          secrets: draft.secrets,
          triggers: draft.triggers,
          tags: draft.tags,
          session_mode: draft.session_mode,
        });
        setDirty(false);
      }
    } catch {
      // Error displayed by mutation state
    }
  };

  // Wire up Ctrl+S ref now that handleSave is declared
  saveRef.current = () => { if (dirty || isNew) handleSave(); };

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const handleDelete = async () => {
    if (!workflowId) return;
    try {
      await deleteMut.mutateAsync(workflowId);
      goBack();
    } catch {
      // handled
    }
  };

  const handleExport = async () => {
    try {
      await exportMut.mutateAsync();
      setShowExport(true);
    } catch {
      // handled
    }
  };

  // Step update helper
  const updateStep = useCallback((index: number, patch: Partial<WorkflowStep>) => {
    setDraft((prev) => {
      const steps = (prev.steps || []).map((s, i) => (i === index ? { ...s, ...patch } : s));
      return { ...prev, steps };
    });
    setDirty(true);
  }, []);

  const deleteStep = useCallback((index: number) => {
    setDraft((prev) => ({
      ...prev,
      steps: (prev.steps || []).filter((_, i) => i !== index),
    }));
    setDirty(true);
    setSelectedStepIndex(null);
  }, []);

  if (isLoading && !isNew) {
    return (
      <div className="flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const tabs = [
    { key: "definition", label: "Definition" },
    ...(isNew ? [] : [
      { key: "runs", label: "Runs" },
      { key: "yaml", label: "YAML" },
    ]),
  ];

  const showingPicker = isNew && (showGallery || showYamlImport);
  const isYaml = activeTab === "yaml";
  const isRuns = activeTab === "runs";
  const selectedStep = selectedStepIndex !== null ? (draft.steps || [])[selectedStepIndex] : null;
  const priorStepIds = selectedStepIndex !== null
    ? (draft.steps || []).slice(0, selectedStepIndex).map((s) => s.id)
    : [];

  return (
    <div style={{ overflow: "auto", flex: 1, display: "flex", flexDirection: "column", background: t.surface }}>
      <PageHeader variant="detail" title={isNew ? "New Workflow" : draft.name || "Workflow"} backTo="/admin/workflows" />

      {/* Header */}
      <WorkflowHeader
        name={draft.name || ""}
        isNew={isNew}
        dirty={dirty}
        isFileBased={isFileBased}
        sourceType={existing?.source_type}
        sourcePath={existing?.source_path}
        showingPicker={showingPicker}
        onBack={goBack}
        onSave={handleSave}
        onDelete={() => setShowDeleteConfirm(true)}
        onClone={handleClone}
        onExport={handleExport}
        saving={createMut.isPending || updateMut.isPending}
        t={t}
      />

      {/* Error banner */}
      {(createMut.isError || updateMut.isError || deleteMut.isError) && (
        <div style={{
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
          padding: 10, margin: "0 16px", marginTop: 8, borderRadius: 8, color: t.danger, fontSize: 12,
        }}>
          {(createMut.error || updateMut.error || deleteMut.error)?.message || "Operation failed"}
        </div>
      )}

      {/* Tabs (not for new workflows) */}
      {!isNew && (
        <div style={{ padding: "8px 16px 0" }}>
          <TabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />
        </div>
      )}

      {/* Content area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>

        {/* Template gallery */}
        {isNew && showGallery && !showYamlImport && (
          <div style={{ padding: 16, maxWidth: 900 }}>
            <WorkflowTemplateGallery
              onSelectTemplate={(tmpl) => {
                setDraft((prev) => ({ ...prev, ...tmpl }));
                setDirty(true);
                setShowGallery(false);
              }}
              onStartBlank={() => setShowGallery(false)}
              onImportYaml={() => { setShowGallery(false); setShowYamlImport(true); }}
            />
          </div>
        )}

        {/* YAML import */}
        {isNew && showYamlImport && (
          <div style={{ padding: 16, maxWidth: 800 }}>
            <YamlImport
              onImport={(parsed) => {
                setDraft((prev) => ({ ...prev, ...parsed }));
                setDirty(true);
                setShowYamlImport(false);
              }}
              onCancel={() => { setShowYamlImport(false); setShowGallery(true); }}
              t={t}
            />
          </div>
        )}

        {/* Definition tab — two-pane layout */}
        {activeTab === "definition" && !showingPicker && (
          isMobile ? (
            <MobileDefinitionEditor
              draft={draft}
              update={update}
              isNew={isNew}
              workflowSecrets={draft.secrets || []}
              t={t}
            />
          ) : (
            <DesktopDefinitionEditor
              draft={draft}
              update={update}
              updateStep={updateStep}
              deleteStep={deleteStep}
              isNew={isNew}
              selectedStepIndex={selectedStepIndex}
              onSelectStep={setSelectedStepIndex}
              selectedStep={selectedStep}
              priorStepIds={priorStepIds}
              workflowSecrets={draft.secrets || []}
              t={t}
            />
          )
        )}

        {/* Runs tab */}
        {activeTab === "runs" && workflowId && !isNew && (
          <div style={{ padding: "12px 16px", flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            <WorkflowRunsTab workflowId={workflowId} initialRunId={runParam} />
          </div>
        )}

        {/* YAML tab */}
        {activeTab === "yaml" && !isNew && (
          <div style={{ padding: 16, flex: 1, display: "flex", flexDirection: "column", minHeight: 0, maxWidth: 1200 }}>
            <YamlEditorTab draft={draft} onUpdate={(patch) => update(patch)} t={t} />
          </div>
        )}
      </div>

      {/* Export YAML modal */}
      {showExport && exportMut.data && (
        <ExportModal
          yaml={exportMut.data}
          onClose={() => setShowExport(false)}
          t={t}
        />
      )}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete Workflow"
        message={`Delete workflow "${draft.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={() => { setShowDeleteConfirm(false); handleDelete(); }}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Desktop definition editor — two-pane layout
// ---------------------------------------------------------------------------

function DesktopDefinitionEditor({ draft, update, updateStep, deleteStep, isNew, selectedStepIndex, onSelectStep, selectedStep, priorStepIds, workflowSecrets, t }: {
  draft: Partial<Workflow>;
  update: (patch: Partial<Workflow>) => void;
  updateStep: (index: number, patch: Partial<WorkflowStep>) => void;
  deleteStep: (index: number) => void;
  isNew: boolean;
  selectedStepIndex: number | null;
  onSelectStep: (index: number | null) => void;
  selectedStep: WorkflowStep | null;
  priorStepIds: string[];
  workflowSecrets: string[];
  t: ReturnType<typeof useThemeTokens>;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "row", flex: 1, minHeight: 0,
      padding: "12px 16px",
      gap: 16,
    }}>
      {/* Left pane: config + step list */}
      <div style={{
        width: 320, flexShrink: 0,
        overflow: "auto",
        display: "flex", flexDirection: "column", gap: 12,
        paddingRight: 4,
      }}>
        <WorkflowIdentitySection
          draft={draft}
          update={update}
          isNew={isNew}
          t={t}
        />
        <WorkflowStepList
          steps={draft.steps || []}
          selectedIndex={selectedStepIndex}
          onSelect={(i) => onSelectStep(i)}
          onChange={(steps) => update({ steps })}
          t={t}
        />
      </div>

      {/* Right pane: step detail */}
      <div style={{
        flex: 1, minWidth: 0,
        overflow: "auto",
        display: "flex", flexDirection: "column",
        background: t.codeBg,
        borderRadius: 10,
        border: `1px solid ${t.surfaceBorder}`,
        padding: 16,
      }}>
        {selectedStep && selectedStepIndex !== null ? (
          <WorkflowStepDetail
            step={selectedStep}
            stepIndex={selectedStepIndex}
            onChange={(patch) => updateStep(selectedStepIndex, patch)}
            onDelete={() => deleteStep(selectedStepIndex)}
            priorStepIds={priorStepIds}
            workflowSecrets={workflowSecrets}
            t={t}
          />
        ) : (
          <StepDetailEmptyState t={t} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mobile definition editor — accordion-style
// ---------------------------------------------------------------------------

function MobileDefinitionEditor({ draft, update, isNew, workflowSecrets, t }: {
  draft: Partial<Workflow>;
  update: (patch: Partial<Workflow>) => void;
  isNew: boolean;
  workflowSecrets: string[];
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const steps = draft.steps || [];

  const updateStep = useCallback((index: number, patch: Partial<WorkflowStep>) => {
    const next = steps.map((s, i) => (i === index ? { ...s, ...patch } : s));
    update({ steps: next });
  }, [steps, update]);

  const deleteStep = useCallback((index: number) => {
    update({ steps: steps.filter((_, i) => i !== index) });
    setExpandedStep(null);
  }, [steps, update]);

  return (
    <div style={{ padding: 16, overflow: "auto" }}>
      <div style={{ gap: 12 }}>
        <WorkflowIdentitySection
          draft={draft}
          update={update}
          isNew={isNew}
          t={t}
        />

        {/* Steps as accordion */}
        <WorkflowStepList
          steps={steps}
          selectedIndex={expandedStep}
          onSelect={(i) => setExpandedStep(expandedStep === i ? null : i)}
          onChange={(newSteps) => update({ steps: newSteps })}
          t={t}
        />

        {/* Expanded step detail inline */}
        {expandedStep !== null && steps[expandedStep] && (
          <div style={{
            borderRadius: 10, border: `1px solid ${t.surfaceBorder}`,
            background: t.codeBg, padding: 12,
          }}>
            <WorkflowStepDetail
              step={steps[expandedStep]}
              stepIndex={expandedStep}
              onChange={(patch) => updateStep(expandedStep, patch)}
              onDelete={() => deleteStep(expandedStep)}
              priorStepIds={steps.slice(0, expandedStep).map((s) => s.id)}
              workflowSecrets={workflowSecrets}
              t={t}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// YAML import (paste to create)
// ---------------------------------------------------------------------------

function YamlImport({ onImport, onCancel, t }: {
  onImport: (parsed: Partial<Workflow>) => void;
  onCancel: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [yamlText, setYamlText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  const handleChange = useCallback((text: string) => {
    setYamlText(text);
    if (!text.trim()) {
      setParseError(null);
      return;
    }
    try {
      const parsed = yaml.load(text);
      if (!parsed || typeof parsed !== "object") {
        setParseError("YAML must be an object");
      } else {
        setParseError(null);
      }
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : "Invalid YAML");
    }
  }, []);

  const handleImport = () => {
    try {
      const parsed = yaml.load(yamlText) as Record<string, unknown> | null;
      if (!parsed || typeof parsed !== "object") {
        setParseError("YAML must be an object");
        return;
      }
      onImport({
        id: (parsed.id as string) || "",
        name: (parsed.name as string) || "",
        description: (parsed.description as string) || "",
        steps: (parsed.steps as WorkflowStep[]) || [],
        params: (parsed.params as Record<string, unknown>) || {},
        defaults: (parsed.defaults as Record<string, unknown>) || {},
        secrets: (parsed.secrets as string[]) || [],
        triggers: (parsed.triggers as Record<string, boolean>) || {},
        tags: (parsed.tags as string[]) || [],
        session_mode: (parsed.session_mode as string) || "isolated",
      });
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : "Invalid YAML");
    }
  };

  return (
    <div style={{ gap: 12 }}>
      <div style={{ gap: 4 }}>
        <span style={{ color: t.text, fontSize: 18, fontWeight: "700" }}>Import YAML</span>
        <span style={{ color: t.textMuted, fontSize: 13 }}>Paste a workflow YAML definition below.</span>
      </div>
      <YamlSyntaxEditor
        value={yamlText}
        onChange={handleChange}
        parseError={parseError}
        t={t}
        minHeight={300}
      />
      <div style={{ display: "flex", flexDirection: "row", gap: 8, justifyContent: "flex-end" }}>
        <button type="button"
          onClick={onCancel}
          style={{
            paddingInline: 12, paddingBlock: 6, borderRadius: 6,
            borderWidth: 1, borderColor: t.surfaceBorder,
          }}
        >
          <span style={{ color: t.textMuted, fontSize: 12 }}>Back</span>
        </button>
        <button type="button"
          onClick={handleImport}
          disabled={!yamlText.trim() || !!parseError}
          style={{
            paddingInline: 12, paddingBlock: 6, borderRadius: 6,
            backgroundColor: yamlText.trim() && !parseError ? t.accent : t.surfaceBorder,
            opacity: yamlText.trim() && !parseError ? 1 : 0.5,
          }}
        >
          <span style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>Import</span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// YAML editor tab
// ---------------------------------------------------------------------------

function draftToYamlObj(draft: Partial<Workflow>) {
  const obj: Record<string, unknown> = {};
  if (draft.id) obj.id = draft.id;
  if (draft.name) obj.name = draft.name;
  if (draft.description) obj.description = draft.description;
  if (draft.session_mode && draft.session_mode !== "isolated") obj.session_mode = draft.session_mode;
  if (draft.tags && draft.tags.length > 0) obj.tags = draft.tags;
  if (draft.params && Object.keys(draft.params).length > 0) obj.params = draft.params;
  if (draft.secrets && draft.secrets.length > 0) obj.secrets = draft.secrets;
  if (draft.defaults && Object.keys(draft.defaults).length > 0) obj.defaults = draft.defaults;
  if (draft.triggers && Object.keys(draft.triggers).length > 0) obj.triggers = draft.triggers;
  if (draft.steps && draft.steps.length > 0) obj.steps = draft.steps;
  return obj;
}

function YamlEditorTab({ draft, onUpdate, t }: {
  draft: Partial<Workflow>;
  onUpdate: (patch: Partial<Workflow>) => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [yamlText, setYamlText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [internalEdit, setInternalEdit] = useState(false);

  useEffect(() => {
    if (internalEdit) {
      setInternalEdit(false);
      return;
    }
    try {
      const text = yaml.dump(draftToYamlObj(draft), {
        lineWidth: 120, noRefs: true, quotingType: '"', forceQuotes: false,
      });
      setYamlText(text);
      setParseError(null);
    } catch {
      // Keep existing text
    }
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((text: string) => {
    setYamlText(text);
    try {
      const parsed = yaml.load(text) as Record<string, unknown> | null;
      if (!parsed || typeof parsed !== "object") {
        setParseError("YAML must be an object");
        return;
      }
      setParseError(null);
      setInternalEdit(true);
      onUpdate({
        id: (parsed.id as string) || draft.id,
        name: (parsed.name as string) || "",
        description: (parsed.description as string) || "",
        steps: (parsed.steps as WorkflowStep[]) || [],
        params: (parsed.params as Record<string, unknown>) || {},
        defaults: (parsed.defaults as Record<string, unknown>) || {},
        secrets: (parsed.secrets as string[]) || [],
        triggers: (parsed.triggers as Record<string, boolean>) || {},
        tags: (parsed.tags as string[]) || [],
        session_mode: (parsed.session_mode as string) || "isolated",
      });
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : "Invalid YAML");
    }
  }, [draft.id, onUpdate]);

  return (
    <YamlSyntaxEditor
      value={yamlText}
      onChange={handleChange}
      parseError={parseError}
      t={t}
    />
  );
}

// ---------------------------------------------------------------------------
// Export YAML modal
// ---------------------------------------------------------------------------

function ExportModal({ yaml, onClose, t }: {
  yaml: string;
  onClose: () => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(yaml);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 10000,
        }}
      />
      <div style={{
        position: "fixed", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        width: "min(90vw, 600px)", maxHeight: "80vh",
        background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 12, zIndex: 10001,
        display: "flex", flexDirection: "column",
        boxShadow: `0 20px 60px ${t.overlayLight}`,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderBottom: `1px solid ${t.surfaceBorder}`,
        }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Export YAML</span>
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button type="button"
              onClick={handleCopy}
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                paddingInline: 10, paddingBlock: 4, borderRadius: 6,
                backgroundColor: t.accentSubtle, borderWidth: 1, borderColor: t.accentBorder,
              }}
            >
              <Copy size={12} color={t.accent} />
              <span style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>
                {copied ? "Copied!" : "Copy"}
              </span>
            </button>
            <button type="button" onClick={onClose}>
              <XIcon size={18} color={t.textMuted} />
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
          <YamlSyntaxViewer value={yaml} t={t} />
        </div>
      </div>
    </>
  );
}
