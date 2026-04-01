import { useState, useEffect, useCallback } from "react";
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function WorkflowDetailPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { workflowId } = useLocalSearchParams<{ workflowId: string }>();
  const isNew = workflowId === "new";

  const { data: existing, isLoading } = useWorkflow(isNew ? undefined : workflowId);
  const createMut = useCreateWorkflow();
  const updateMut = useUpdateWorkflow(workflowId || "");
  const deleteMut = useDeleteWorkflow();
  const exportMut = useExportWorkflow(workflowId || "");

  const [activeTab, setActiveTab] = useState<string>("definition");
  const [draft, setDraft] = useState<Partial<Workflow>>({
    id: "", name: "", description: "",
    steps: [], params: {}, defaults: {},
    secrets: [], triggers: {}, tags: [],
    session_mode: "isolated",
  });
  const [dirty, setDirty] = useState(false);
  const [showExport, setShowExport] = useState(false);

  const isFileBased = existing?.source_type === "file" || existing?.source_type === "integration";

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
    ...(isNew ? [] : [{ key: "runs", label: "Runs" }]),
  ];

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 14, width: "100%", outline: "none",
  };

  return (
    <div style={{ overflow: "auto", flex: 1 }}>
      <MobileHeader title={isNew ? "New Workflow" : draft.name || "Workflow"} />
      <div style={{ padding: 16, maxWidth: 800 }}>
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
            {/* Export YAML */}
            {!isNew && (
              <Pressable
                onPress={handleExport}
                style={{
                  flexDirection: "row", alignItems: "center", gap: 4,
                  paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                  backgroundColor: t.surfaceRaised, borderWidth: 1, borderColor: t.surfaceBorder,
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

        {activeTab === "definition" && (
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
              <FormRow label="Session Mode" description="How step conversations relate to each other">
                <SelectInput
                  value={draft.session_mode || "isolated"}
                  onChange={(v) => update({ session_mode: v })}
                  options={[
                    { label: "Isolated — each step gets fresh session", value: "isolated" },
                    { label: "Shared — all steps share one conversation", value: "shared" },
                  ]}
                />
              </FormRow>
              <FormRow label="Secrets" description="Comma-separated secret names available to steps">
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
            <Section title="Triggers" description="How this workflow can be invoked">
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
          <WorkflowRunsTab workflowId={workflowId} />
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
        background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 12, zIndex: 10001,
        display: "flex", flexDirection: "column",
        boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
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
