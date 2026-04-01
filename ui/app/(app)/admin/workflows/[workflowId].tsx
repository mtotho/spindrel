import { useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import {
  useWorkflow,
  useCreateWorkflow,
  useUpdateWorkflow,
  useDeleteWorkflow,
} from "@/src/api/hooks/useWorkflows";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Save, Trash2, ArrowLeft, Info,
} from "lucide-react";
import { Section, FormRow, SelectInput, TabBar } from "@/src/components/shared/FormControls";
import type { Workflow } from "@/src/types/api";
import WorkflowRunsTab from "./WorkflowRunsTab";

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

  const [activeTab, setActiveTab] = useState<string>("definition");
  const [draft, setDraft] = useState<Partial<Workflow>>({
    id: "", name: "", description: "",
    steps: [], params: {}, defaults: {},
    secrets: [], triggers: {}, tags: [],
    session_mode: "isolated",
  });
  const [dirty, setDirty] = useState(false);

  // JSON text editors for complex fields
  const [stepsText, setStepsText] = useState("[]");
  const [paramsText, setParamsText] = useState("{}");
  const [defaultsText, setDefaultsText] = useState("{}");
  const [triggersText, setTriggersText] = useState("{}");

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
      setStepsText(JSON.stringify(existing.steps || [], null, 2));
      setParamsText(JSON.stringify(existing.params || {}, null, 2));
      setDefaultsText(JSON.stringify(existing.defaults || {}, null, 2));
      setTriggersText(JSON.stringify(existing.triggers || {}, null, 2));
    }
  }, [existing, isNew]);

  const update = useCallback((patch: Partial<Workflow>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  }, []);

  const handleSave = async () => {
    // Parse JSON fields
    let steps, params, defaults, triggers;
    try {
      steps = JSON.parse(stepsText);
      params = JSON.parse(paramsText);
      defaults = JSON.parse(defaultsText);
      triggers = JSON.parse(triggersText);
    } catch {
      alert("Invalid JSON in one of the fields. Please fix before saving.");
      return;
    }

    try {
      if (isNew) {
        await createMut.mutateAsync({
          id: draft.id || "",
          name: draft.name || "",
          description: draft.description || undefined,
          steps,
          params,
          defaults,
          secrets: draft.secrets || [],
          triggers,
          tags: draft.tags || [],
          session_mode: draft.session_mode || "isolated",
        } as Workflow);
        router.back();
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || undefined,
          steps,
          params,
          defaults,
          secrets: draft.secrets,
          triggers,
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
      router.back();
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
            onPress={() => router.back()}
            style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <Text style={{ color: t.textMuted, fontSize: 13 }}>Back</Text>
          </Pressable>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!isNew && !isFileBased && (
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
            {!isFileBased && (
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
                  {isNew ? "Create" : "Save"}
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
            <Info size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              This workflow is managed by a {existing?.source_type} file
              {existing?.source_path ? ` (${existing.source_path})` : ""}.
              Edit the source YAML to make changes.
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
          <DefinitionTab
            t={t}
            draft={draft}
            update={update}
            isNew={isNew}
            isFileBased={!!isFileBased}
            stepsText={stepsText}
            setStepsText={(v) => { setStepsText(v); setDirty(true); }}
            paramsText={paramsText}
            setParamsText={(v) => { setParamsText(v); setDirty(true); }}
            defaultsText={defaultsText}
            setDefaultsText={(v) => { setDefaultsText(v); setDirty(true); }}
            triggersText={triggersText}
            setTriggersText={(v) => { setTriggersText(v); setDirty(true); }}
          />
        )}

        {activeTab === "runs" && workflowId && !isNew && (
          <WorkflowRunsTab workflowId={workflowId} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Definition form
// ---------------------------------------------------------------------------

function DefinitionTab({
  t, draft, update, isNew, isFileBased,
  stepsText, setStepsText,
  paramsText, setParamsText,
  defaultsText, setDefaultsText,
  triggersText, setTriggersText,
}: {
  t: ThemeTokens;
  draft: Partial<Workflow>;
  update: (patch: Partial<Workflow>) => void;
  isNew: boolean;
  isFileBased: boolean;
  stepsText: string;
  setStepsText: (v: string) => void;
  paramsText: string;
  setParamsText: (v: string) => void;
  defaultsText: string;
  setDefaultsText: (v: string) => void;
  triggersText: string;
  setTriggersText: (v: string) => void;
}) {
  const disabled = isFileBased;
  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 14, width: "100%", outline: "none",
    opacity: disabled ? 0.6 : 1,
    cursor: disabled ? "not-allowed" : undefined,
  };
  const textareaStyle: React.CSSProperties = {
    ...inputStyle, fontFamily: "monospace", fontSize: 12,
    minHeight: 120, resize: "vertical" as const,
  };

  return (
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
              disabled={disabled}
            />
          </FormRow>
        )}
        <FormRow label="Name">
          <input
            value={draft.name || ""}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="My Workflow"
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
        <FormRow label="Description">
          <input
            value={draft.description || ""}
            onChange={(e) => update({ description: e.target.value })}
            placeholder="What this workflow does..."
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
        <FormRow label="Tags" description="Comma-separated labels">
          <input
            value={(draft.tags || []).join(", ")}
            onChange={(e) => update({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="ops, monitoring"
            style={inputStyle}
            disabled={disabled}
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
            style={disabled ? { opacity: 0.6, pointerEvents: "none" as const } : undefined}
          />
        </FormRow>
        <FormRow label="Secrets" description="Comma-separated secret names available to steps">
          <input
            value={(draft.secrets || []).join(", ")}
            onChange={(e) => update({ secrets: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="API_KEY, DB_PASSWORD"
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
      </Section>

      {/* Parameters (JSON) */}
      <Section title="Parameters" description="Parameter definitions (JSON)">
        <JsonEditor
          value={paramsText}
          onChange={setParamsText}
          style={textareaStyle}
          disabled={disabled}
          placeholder='{"topic": {"type": "string", "required": true, "description": "..."}}'
        />
      </Section>

      {/* Defaults (JSON) */}
      <Section title="Defaults" description="Default execution config: model, bot_id, timeout, carapaces, tools">
        <JsonEditor
          value={defaultsText}
          onChange={setDefaultsText}
          style={textareaStyle}
          disabled={disabled}
          placeholder='{"bot_id": "my-bot", "model": "gemini/gemini-2.5-flash", "timeout": 120}'
        />
      </Section>

      {/* Triggers */}
      <Section title="Triggers" description="How this workflow can be invoked">
        <JsonEditor
          value={triggersText}
          onChange={setTriggersText}
          style={{ ...textareaStyle, minHeight: 60 }}
          disabled={disabled}
          placeholder='{"tool": true, "api": true, "heartbeat": false}'
        />
      </Section>

      {/* Steps (JSON) */}
      <Section title="Steps" description="Step definitions (JSON array)">
        <JsonEditor
          value={stepsText}
          onChange={setStepsText}
          style={{ ...textareaStyle, minHeight: 200 }}
          disabled={disabled}
          placeholder='[{"id": "step1", "prompt": "Do the thing with {{param}}."}]'
        />
        {/* Step preview */}
        <StepPreview stepsText={stepsText} t={t} />
      </Section>
    </View>
  );
}

// ---------------------------------------------------------------------------
// JSON editor with validation
// ---------------------------------------------------------------------------

function JsonEditor({
  value, onChange, style, disabled, placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  style: React.CSSProperties;
  disabled: boolean;
  placeholder?: string;
}) {
  const t = useThemeTokens();
  let isValid = true;
  try { JSON.parse(value); } catch { isValid = false; }

  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          ...style,
          borderColor: isValid ? t.inputBorder : t.danger,
        }}
        disabled={disabled}
        placeholder={placeholder}
        spellCheck={false}
      />
      {!isValid && value.trim() && (
        <div style={{ color: t.danger, fontSize: 11, marginTop: 2 }}>Invalid JSON</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step preview cards
// ---------------------------------------------------------------------------

function StepPreview({ stepsText, t }: { stepsText: string; t: ThemeTokens }) {
  let steps: any[];
  try { steps = JSON.parse(stepsText); } catch { return null; }
  if (!Array.isArray(steps) || steps.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
      <div style={{ fontSize: 11, color: t.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
        Step Preview
      </div>
      {steps.map((step, i) => (
        <div
          key={step.id || i}
          style={{
            display: "flex", alignItems: "flex-start", gap: 10,
            padding: "8px 12px", borderRadius: 8,
            background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <div style={{
            width: 22, height: 22, borderRadius: 11, flexShrink: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
            fontSize: 11, fontWeight: 700, color: t.accent,
          }}>
            {i + 1}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                {step.id || `step_${i}`}
              </span>
              {step.requires_approval && (
                <span style={{
                  fontSize: 10, padding: "1px 5px", borderRadius: 3,
                  background: t.warningSubtle, border: `1px solid ${t.warningBorder}`, color: t.warning,
                }}>
                  approval
                </span>
              )}
              {step.on_failure && step.on_failure !== "abort" && (
                <span style={{
                  fontSize: 10, padding: "1px 5px", borderRadius: 3,
                  background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`, color: t.textDim,
                }}>
                  on_failure: {step.on_failure}
                </span>
              )}
              {step.when && (
                <span style={{
                  fontSize: 10, padding: "1px 5px", borderRadius: 3,
                  background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`, color: t.purple,
                }}>
                  conditional
                </span>
              )}
            </div>
            <div style={{
              fontSize: 12, color: t.textMuted, marginTop: 3,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {(step.prompt || "").slice(0, 120)}
            </div>
            {(step.tools || step.secrets || step.model) && (
              <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                {step.tools?.map((tool: string) => (
                  <span key={tool} style={{
                    fontSize: 10, padding: "1px 4px", borderRadius: 3,
                    background: t.surfaceOverlay, color: t.textDim,
                  }}>
                    {tool}
                  </span>
                ))}
                {step.model && (
                  <span style={{
                    fontSize: 10, padding: "1px 4px", borderRadius: 3,
                    background: t.surfaceOverlay, color: t.textDim,
                  }}>
                    model: {step.model}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
