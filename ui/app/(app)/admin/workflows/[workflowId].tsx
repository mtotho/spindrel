import { useState, useEffect, useCallback, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  useWorkflow,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
  useExportWorkflow,
} from "@/src/api/hooks/useWorkflows";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { Save, Trash2, ArrowLeft, Info, Download, Copy, X as XIcon, Unlink } from "lucide-react";
import { Section, FormRow, SelectInput, TabBar } from "@/src/components/shared/FormControls";
import type { Workflow, WorkflowStep } from "@/src/types/api";
import WorkflowRunsTab from "./WorkflowRunsTab";
import { WorkflowStepEditor } from "./WorkflowStepEditor";
import { DefaultsEditor, ParamsEditor, TriggersEditor } from "./WorkflowFormParts";
import { WorkflowTemplateGallery } from "./WorkflowTemplateGallery";
import { HelpTooltip } from "./HelpTooltip";
import yaml from "js-yaml";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WorkflowDetailPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { workflowId, tab: tabParam, run: runParam, clone: cloneParam } = useLocalSearchParams<{
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

  const isFileBased = existing?.source_type === "file" || existing?.source_type === "integration";

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

  const goBack = () => router.push("/admin/workflows" as any);

  const handleClone = () => {
    // Generate a unique clone ID
    const baseId = (draft.id || "workflow") + "-copy";
    const cloneData: Partial<Workflow> = {
      id: baseId,
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
    router.push(`/admin/workflows/new?clone=${encodeURIComponent(JSON.stringify(cloneData))}` as any);
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

  const handleDelete = async () => {
    if (!workflowId) return;
    const ok = Platform.OS === "web"
      ? window.confirm(`Delete workflow "${draft.name}"?`)
      : true;
    if (!ok) return;
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

  if (isLoading && !isNew) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const tabs = [
    { key: "definition", label: "Definition" },
    ...(isNew ? [] : [
      { key: "runs", label: "Runs" },
      { key: "yaml", label: "YAML" },
    ]),
  ];

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 14, width: "100%", outline: "none",
  };

  const isYaml = activeTab === "yaml";
  const isRuns = activeTab === "runs";
  const needsFlex = isYaml || isRuns;

  return (
    <div style={{ overflow: "auto", flex: 1, display: "flex", flexDirection: "column", background: t.surface }}>
      <MobileHeader title={isNew ? "New Workflow" : draft.name || "Workflow"} />
      <div style={{
        padding: 16,
        maxWidth: isRuns ? 1100 : isYaml ? 1200 : 800,
        flex: needsFlex ? 1 : undefined,
        minHeight: needsFlex ? 0 : undefined,
        display: needsFlex ? "flex" : undefined,
        flexDirection: needsFlex ? "column" : undefined,
      }}>
        {/* Top bar: back + actions */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 16,
        }}>
          <Pressable
            onPress={goBack}
            style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <Text style={{ color: t.textMuted, fontSize: 13 }}>Workflows</Text>
          </Pressable>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!isNew && (
              <Pressable
                onPress={handleClone}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: t.codeBg, borderWidth: 1, borderColor: t.surfaceBorder,
                }}
              >
                <Copy size={14} color={t.textMuted} />
                <Text style={{ color: t.textMuted, fontSize: 12 }}>Clone</Text>
              </Pressable>
            )}
            {/* Export YAML */}
            {!isNew && (
              <Pressable
                onPress={handleExport}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: t.codeBg, borderWidth: 1, borderColor: t.surfaceBorder,
                }}
              >
                <Download size={14} color={t.textMuted} />
                <Text style={{ color: t.textMuted, fontSize: 12 }}>Export</Text>
              </Pressable>
            )}
            {!isNew && (
              <Pressable
                onPress={handleDelete}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: t.dangerSubtle, borderWidth: 1, borderColor: t.dangerBorder,
                }}
              >
                <Trash2 size={14} color={t.danger} />
                <Text style={{ color: t.danger, fontSize: 12 }}>Delete</Text>
              </Pressable>
            )}
            {!(isNew && (showGallery || showYamlImport)) && (
              <Pressable
                onPress={handleSave}
                disabled={!dirty && !isNew}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: dirty || isNew ? t.accent : t.surfaceBorder,
                  opacity: dirty || isNew ? 1 : 0.5,
                }}
              >
                <Save size={14} color="#fff" />
                <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                  {isNew ? "Create" : isFileBased && dirty ? "Detach & Save" : "Save"}
                </Text>
              </Pressable>
            )}
          </div>
        </div>

        {/* Error banner */}
        {(createMut.isError || updateMut.isError || deleteMut.isError) && (
          <div style={{
            background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
            padding: 10, borderRadius: 8, marginBottom: 12, color: t.danger, fontSize: 12,
          }}>
            {(createMut.error || updateMut.error || deleteMut.error)?.message || "Operation failed"}
          </div>
        )}

        {/* File-managed banner */}
        {isFileBased && (
          <div style={{
            display: "flex", alignItems: "flex-start", gap: 8,
            background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
            padding: 10, borderRadius: 8, marginBottom: 16, color: t.accent, fontSize: 12,
          }}>
            <Unlink size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              Sourced from {existing?.source_type} file
              {existing?.source_path ? ` (${existing.source_path})` : ""}.
              You can edit freely — saving will detach from the file and make this a user-managed workflow.
            </span>
          </div>
        )}

        {/* Tabs */}
        {!isNew && (
          <div style={{ marginBottom: 16 }}>
            <TabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />
          </div>
        )}

        {/* Template gallery for new workflows */}
        {isNew && showGallery && !showYamlImport && (
          <WorkflowTemplateGallery
            onSelectTemplate={(tmpl) => {
              setDraft((prev) => ({ ...prev, ...tmpl }));
              setDirty(true);
              setShowGallery(false);
            }}
            onStartBlank={() => setShowGallery(false)}
            onImportYaml={() => { setShowGallery(false); setShowYamlImport(true); }}
          />
        )}

        {/* YAML import for new workflows */}
        {isNew && showYamlImport && (
          <YamlImport
            onImport={(parsed) => {
              setDraft((prev) => ({ ...prev, ...parsed }));
              setDirty(true);
              setShowYamlImport(false);
            }}
            onCancel={() => { setShowYamlImport(false); setShowGallery(true); }}
            t={t}
          />
        )}

        {activeTab === "definition" && !(isNew && (showGallery || showYamlImport)) && (
          <View style={{ gap: 20 }}>
            {/* Identity */}
            <Section title="Identity">
              {isNew && (
                <FormRow label="ID" description="Unique slug identifier (lowercase, hyphens)">
                  <input
                    value={draft.id || ""}
                    onChange={(e) => update({ id: e.target.value })}
                    placeholder="my-workflow"
                    style={inputStyle}
                  />
                </FormRow>
              )}
              <FormRow label="Name">
                <input
                  value={draft.name || ""}
                  onChange={(e) => update({ name: e.target.value })}
                  placeholder="My Workflow"
                  style={inputStyle}
                />
              </FormRow>
              <FormRow label="Description">
                <input
                  value={draft.description || ""}
                  onChange={(e) => update({ description: e.target.value })}
                  placeholder="What this workflow does..."
                  style={inputStyle}
                />
              </FormRow>
              <FormRow label="Tags" description="Comma-separated labels">
                <input
                  value={(draft.tags || []).join(", ")}
                  onChange={(e) => update({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="ops, monitoring"
                  style={inputStyle}
                />
              </FormRow>
            </Section>

            {/* Execution */}
            <Section title="Execution">
              <FormRow label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Session Mode <HelpTooltip text="Isolated: each step gets fresh context. Shared: all steps share one conversation channel — outputs appear in chat." /></span>} description="How step conversations relate to each other">
                <SelectInput
                  value={draft.session_mode || "isolated"}
                  onChange={(v) => update({ session_mode: v })}
                  options={[
                    { label: "Isolated — each step gets fresh context", value: "isolated" },
                    { label: "Shared — all steps share one conversation", value: "shared" },
                  ]}
                />
              </FormRow>
              <FormRow label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Secrets <HelpTooltip text='Secret names that steps can reference via {{secrets.NAME}}. Values are stored in server settings, not in the workflow.' /></span>} description="Comma-separated secret names available to steps">
                <input
                  value={(draft.secrets || []).join(", ")}
                  onChange={(e) => update({ secrets: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="API_KEY, DB_PASSWORD"
                  style={inputStyle}
                />
              </FormRow>
            </Section>

            {/* Parameters */}
            <Section title="Parameters" description="Input parameters for workflow triggers">
              <ParamsEditor
                value={draft.params || {}}
                onChange={(v) => update({ params: v })}
              />
            </Section>

            {/* Defaults */}
            <Section title="Defaults" description="Default execution config for all steps">
              <DefaultsEditor
                value={draft.defaults || {}}
                onChange={(v) => update({ defaults: v })}
              />
            </Section>

            {/* Triggers */}
            <Section title={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Triggers <HelpTooltip text="Controls which sources can start this workflow. Disable a trigger to prevent that source from running it." /></span>} description="How this workflow can be invoked">
              <TriggersEditor
                value={(draft.triggers || {}) as Record<string, boolean>}
                onChange={(v) => update({ triggers: v })}
              />
            </Section>

            {/* Steps */}
            <Section title="Steps" description="Workflow step definitions">
              <WorkflowStepEditor
                steps={draft.steps || []}
                onChange={(v) => update({ steps: v })}
              />
            </Section>
          </View>
        )}

        {activeTab === "runs" && workflowId && !isNew && (
          <WorkflowRunsTab workflowId={workflowId} initialRunId={runParam} />
        )}

        {activeTab === "yaml" && !isNew && (
          <YamlEditor draft={draft} onUpdate={(patch) => update(patch)} t={t} />
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

  const handleParse = () => {
    try {
      const parsed = yaml.load(yamlText) as Record<string, unknown> | null;
      if (!parsed || typeof parsed !== "object") {
        setParseError("YAML must be an object");
        return;
      }
      setParseError(null);
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
    <View style={{ gap: 12 }}>
      <View style={{ gap: 4 }}>
        <Text style={{ color: t.text, fontSize: 18, fontWeight: "700" }}>
          Import YAML
        </Text>
        <Text style={{ color: t.textMuted, fontSize: 13 }}>
          Paste a workflow YAML definition below.
        </Text>
      </View>

      {parseError && (
        <div style={{
          padding: "6px 10px", borderRadius: 6, fontSize: 12, fontFamily: "monospace",
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`, color: t.danger,
        }}>
          {parseError}
        </div>
      )}

      <textarea
        value={yamlText}
        onChange={(e) => { setYamlText(e.target.value); setParseError(null); }}
        placeholder={"id: my-workflow\nname: My Workflow\nsteps:\n  - id: step_1\n    prompt: Do something..."}
        spellCheck={false}
        style={{
          width: "100%",
          minHeight: 300,
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: "1.6",
          padding: 16,
          borderRadius: 8,
          border: `1px solid ${parseError ? t.dangerBorder : t.inputBorder}`,
          background: t.inputBg,
          color: t.inputText,
          resize: "vertical",
          outline: "none",
          tabSize: 2,
        }}
      />

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Pressable
          onPress={onCancel}
          style={{
            paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
            borderWidth: 1, borderColor: t.surfaceBorder,
          }}
        >
          <Text style={{ color: t.textMuted, fontSize: 12 }}>Back</Text>
        </Pressable>
        <Pressable
          onPress={handleParse}
          disabled={!yamlText.trim()}
          style={{
            paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6,
            backgroundColor: yamlText.trim() ? t.accent : t.surfaceBorder,
            opacity: yamlText.trim() ? 1 : 0.5,
          }}
        >
          <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>Import</Text>
        </Pressable>
      </div>
    </View>
  );
}

// ---------------------------------------------------------------------------
// YAML editor
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

function YamlEditor({ draft, onUpdate, t }: {
  draft: Partial<Workflow>;
  onUpdate: (patch: Partial<Workflow>) => void;
  t: ReturnType<typeof useThemeTokens>;
}) {
  const [yamlText, setYamlText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [internalEdit, setInternalEdit] = useState(false);

  // Sync draft → YAML text (only when draft changes externally, not from our own edits)
  useEffect(() => {
    if (internalEdit) {
      setInternalEdit(false);
      return;
    }
    try {
      const text = yaml.dump(draftToYamlObj(draft), {
        lineWidth: 120,
        noRefs: true,
        quotingType: '"',
        forceQuotes: false,
      });
      setYamlText(text);
      setParseError(null);
    } catch {
      // Keep existing text
    }
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = (text: string) => {
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
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1, minHeight: 0 }}>
      {parseError && (
        <div style={{
          padding: "6px 10px", borderRadius: 6, fontSize: 12, fontFamily: "monospace",
          background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`, color: t.danger,
          flexShrink: 0,
        }}>
          {parseError}
        </div>
      )}
      <textarea
        value={yamlText}
        onChange={(e) => handleChange(e.target.value)}
        spellCheck={false}
        style={{
          width: "100%",
          flex: 1,
          minHeight: 400,
          fontFamily: "monospace",
          fontSize: 13,
          lineHeight: "1.6",
          padding: 16,
          borderRadius: 8,
          border: `1px solid ${parseError ? t.dangerBorder : t.inputBorder}`,
          background: t.inputBg,
          color: t.inputText,
          resize: "none",
          outline: "none",
          tabSize: 2,
        }}
      />
    </div>
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
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          zIndex: 10000,
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
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderBottom: `1px solid ${t.surfaceBorder}`,
        }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Export YAML</span>
          <div style={{ display: "flex", gap: 8 }}>
            <Pressable
              onPress={handleCopy}
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6,
                backgroundColor: t.accentSubtle, borderWidth: 1, borderColor: t.accentBorder,
              }}
            >
              <Copy size={12} color={t.accent} />
              <Text style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>
                {copied ? "Copied!" : "Copy"}
              </Text>
            </Pressable>
            <Pressable onPress={onClose}>
              <XIcon size={18} color={t.textMuted} />
            </Pressable>
          </div>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
          <pre style={{
            margin: 0, fontSize: 12, fontFamily: "monospace",
            color: t.text, whiteSpace: "pre-wrap", wordBreak: "break-word",
          }}>
            {yaml}
          </pre>
        </div>
      </div>
    </>
  );
}
