/**
 * Compact identity & config section for workflow left pane.
 * Collapsible sections: Identity, Execution, Parameters, Defaults, Triggers.
 */
import { useState, useMemo } from "react";
import { View, Text, Pressable } from "react-native";
import { type ThemeTokens } from "@/src/theme/tokens";
import { useSecretValues } from "@/src/api/hooks/useSecretValues";
import { ChevronDown, ChevronRight } from "lucide-react";
import { FormRow, SelectInput, Toggle } from "@/src/components/shared/FormControls";
import type { Workflow } from "@/src/types/api";
import { HelpTooltip } from "./HelpTooltip";
import { SecretChipPicker } from "./SecretChipPicker";
import { DefaultsEditor } from "./WorkflowDefaults";
import { ParamsEditor } from "./WorkflowParams";

interface WorkflowIdentitySectionProps {
  draft: Partial<Workflow>;
  update: (patch: Partial<Workflow>) => void;
  isNew: boolean;
  disabled?: boolean;
  t: ThemeTokens;
}

export function WorkflowIdentitySection({
  draft, update, isNew, disabled, t,
}: WorkflowIdentitySectionProps) {
  const { data: vaultSecrets } = useSecretValues();
  const vaultSecretNames = useMemo(() => (vaultSecrets || []).map((s) => s.name), [vaultSecrets]);

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 13, width: "100%", outline: "none",
  };

  const paramCount = Object.keys(draft.params || {}).length;
  const defaultsCount = Object.keys(draft.defaults || {}).length;

  return (
    <View style={{ gap: 4 }}>
      {/* Identity section — always open */}
      <CollapsibleSection title="Identity" defaultOpen t={t}>
        {isNew && (
          <FormRow label="ID" description="Unique slug (lowercase, hyphens)">
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
        <FormRow label="Tags" description="Comma-separated">
          <input
            value={(draft.tags || []).join(", ")}
            onChange={(e) => update({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="ops, monitoring"
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
      </CollapsibleSection>

      {/* Execution settings */}
      <CollapsibleSection title="Execution" defaultOpen t={t}>
        <FormRow label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Session Mode <HelpTooltip text="Isolated: each step gets fresh context. Shared: steps share one conversation channel." /></span>}>
          <SelectInput
            value={draft.session_mode || "isolated"}
            onChange={(v) => update({ session_mode: v })}
            options={[
              { label: "Isolated", value: "isolated" },
              { label: "Shared", value: "shared" },
            ]}
          />
        </FormRow>
        <FormRow label={<span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>Secrets <HelpTooltip text="Secrets from vault available to workflow steps." /></span>}>
          <SecretChipPicker
            available={vaultSecretNames}
            selected={draft.secrets || []}
            onChange={(v) => update({ secrets: v })}
            t={t}
          />
        </FormRow>
      </CollapsibleSection>

      {/* Parameters */}
      <CollapsibleSection
        title="Parameters"
        badge={paramCount > 0 ? String(paramCount) : undefined}
        defaultOpen={paramCount > 0}
        t={t}
      >
        <ParamsEditor
          value={draft.params || {}}
          onChange={(v) => update({ params: v })}
          disabled={disabled}
        />
      </CollapsibleSection>

      {/* Defaults */}
      <CollapsibleSection
        title="Defaults"
        badge={defaultsCount > 0 ? String(defaultsCount) : undefined}
        defaultOpen={false}
        t={t}
      >
        <Text style={{ color: t.textDim, fontSize: 11, marginBottom: 8, fontStyle: "italic" }}>
          Apply to all steps unless overridden.
        </Text>
        <DefaultsEditor
          value={draft.defaults || {}}
          onChange={(v) => update({ defaults: v })}
          disabled={disabled}
        />
      </CollapsibleSection>

      {/* Triggers */}
      <CollapsibleSection title="Triggers" defaultOpen={false} t={t}>
        <TriggersEditor
          value={(draft.triggers || {}) as Record<string, boolean>}
          onChange={(v) => update({ triggers: v })}
        />
      </CollapsibleSection>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Collapsible section
// ---------------------------------------------------------------------------

function CollapsibleSection({ title, badge, defaultOpen, children, t }: {
  title: string;
  badge?: string;
  defaultOpen: boolean;
  children: React.ReactNode;
  t: ThemeTokens;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div style={{
      borderRadius: 8,
      border: `1px solid ${t.surfaceBorder}`,
      background: t.codeBg,
      overflow: "hidden",
    }}>
      <Pressable
        onPress={() => setOpen(!open)}
        style={{
          flexDirection: "row", alignItems: "center", gap: 6,
          paddingVertical: 8, paddingHorizontal: 10,
        }}
      >
        {open
          ? <ChevronDown size={12} color={t.textMuted} />
          : <ChevronRight size={12} color={t.textMuted} />
        }
        <Text style={{
          fontSize: 11, fontWeight: 700, color: t.textMuted,
          textTransform: "uppercase", letterSpacing: 0.5,
        }}>
          {title}
        </Text>
        {badge && (
          <span style={{
            fontSize: 10, fontWeight: 600, color: t.textDim,
            background: t.surfaceRaised, borderRadius: 8,
            padding: "0px 5px",
          }}>
            {badge}
          </span>
        )}
      </Pressable>
      {open && (
        <div style={{
          padding: "4px 10px 10px",
          display: "flex", flexDirection: "column", gap: 10,
          borderTop: `1px solid ${t.surfaceBorder}`,
        }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline triggers editor (small enough to keep here)
// ---------------------------------------------------------------------------

function TriggersEditor({ value, onChange }: {
  value: Record<string, boolean>;
  onChange: (v: Record<string, boolean>) => void;
}) {
  const update = (key: string, v: boolean) => onChange({ ...value, [key]: v });

  return (
    <View style={{ gap: 4 }}>
      <Toggle value={!!value.tool} onChange={(v) => update("tool", v)} label="Tool" description="Via manage_workflow tool" />
      <Toggle value={!!value.api} onChange={(v) => update("api", v)} label="API" description="Via admin API" />
      <Toggle value={!!value.heartbeat} onChange={(v) => update("heartbeat", v)} label="Heartbeat" description="From heartbeat prompts" />
      <Toggle value={!!value.task} onChange={(v) => update("task", v)} label="Scheduled Task" description="By scheduled tasks" />
    </View>
  );
}
