/**
 * Right pane step editor with three collapsible field groups:
 * Execution, Tools & Context, Control Flow.
 * Fields shown/hidden based on step type.
 */
import { useState, useCallback, useEffect } from "react";

import { type ThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FormRow, Toggle } from "@/src/components/shared/FormControls";
import {
  ChevronDown, ChevronRight, Trash2,
  Bot, Zap, Terminal,
} from "lucide-react";
import type { WorkflowStep } from "@/src/types/api";
import { HelpTooltip } from "./HelpTooltip";
import { SecretChipPicker } from "./SecretChipPicker";
import { WorkflowConditionBuilder } from "./WorkflowConditionBuilder";

interface WorkflowStepDetailProps {
  step: WorkflowStep;
  stepIndex: number;
  onChange: (patch: Partial<WorkflowStep>) => void;
  onDelete: () => void;
  priorStepIds: string[];
  workflowSecrets: string[];
  disabled?: boolean;
  t: ThemeTokens;
}

export function WorkflowStepDetail({
  step, stepIndex, onChange, onDelete, priorStepIds, workflowSecrets, disabled, t,
}: WorkflowStepDetailProps) {
  const stepType = step.type || "agent";

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 13, width: "100%", outline: "none",
    opacity: disabled ? 0.6 : 1,
  };

  const typeColors = {
    agent: { border: t.accent, bg: t.accentSubtle, text: t.accent, icon: Bot },
    tool: { border: t.purple, bg: t.purpleSubtle, text: t.purple, icon: Zap },
    exec: { border: t.warning, bg: t.warningSubtle, text: t.warning, icon: Terminal },
  };
  const tc = typeColors[stepType as keyof typeof typeColors] || typeColors.agent;
  const TypeIcon = tc.icon;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 12,
      overflow: "auto", flex: 1,
    }}>
      {/* Step header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        padding: "8px 0",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4,
            fontSize: 11, padding: "2px 8px", borderRadius: 4,
            background: tc.bg, border: `1px solid ${tc.border}`, color: tc.text,
            fontWeight: 600,
          }}>
            <TypeIcon size={12} />
            {stepType}
          </span>
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
            {step.id}
          </span>
        </div>
        {!disabled && (
          <button
            onClick={onDelete}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              padding: "4px 8px", borderRadius: 5,
              background: "none", border: `1px solid ${t.dangerBorder}`,
              color: t.danger, fontSize: 11, cursor: "pointer",
            }}
          >
            <Trash2 size={11} />
            Delete
          </button>
        )}
      </div>

      {/* Step ID + Type */}
      <div style={{ display: "flex", flexDirection: "row", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <FormRow label="Step ID">
            <input
              value={step.id}
              onChange={(e) => onChange({ id: e.target.value })}
              placeholder="step_1"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>
        </div>
        <div style={{ width: 160 }}>
          <FormRow label="Type">
            <select
              value={stepType}
              onChange={(e) => onChange({ type: e.target.value as WorkflowStep["type"] })}
              style={{ ...inputStyle, cursor: "pointer" }}
              disabled={disabled}
            >
              <option value="agent">Agent</option>
              <option value="tool">Tool</option>
              <option value="exec">Exec</option>
            </select>
          </FormRow>
        </div>
      </div>

      {/* Execution group */}
      <FieldGroup title="Execution" defaultOpen t={t}>
        {/* Tool-specific: tool_name + tool_args */}
        {stepType === "tool" && (
          <>
            <FormRow label="Tool Name" description="Registered tool to call directly">
              <input
                value={step.tool_name || ""}
                onChange={(e) => onChange({ tool_name: e.target.value })}
                placeholder="web_search"
                style={inputStyle}
                disabled={disabled}
              />
            </FormRow>
            <FormRow label="Tool Arguments" description="JSON object. Use {{param}} for substitution.">
              <ToolArgsEditor
                value={step.tool_args}
                onChange={(v) => onChange({ tool_args: v })}
                disabled={disabled}
                t={t}
                inputStyle={inputStyle}
              />
            </FormRow>
          </>
        )}

        {/* Prompt (agent + exec) */}
        {stepType !== "tool" && (
          <FormRow
            label={stepType === "exec" ? "Command" : "Prompt"}
            description={stepType === "exec"
              ? "Shell command. Use {{param}} for substitution."
              : "Use {{param}} for params, {{steps.id.result}} for prior results"
            }
          >
            <textarea
              value={step.prompt || ""}
              onChange={(e) => onChange({ prompt: e.target.value })}
              placeholder={stepType === "exec" ? "curl -s https://api.example.com/status" : "Execute the task..."}
              rows={stepType === "exec" ? 2 : 4}
              style={{
                ...inputStyle, fontFamily: "monospace", fontSize: 12,
                resize: "vertical" as const, minHeight: stepType === "exec" ? 40 : 80,
              }}
              disabled={disabled}
            />
          </FormRow>
        )}

        {/* Exec-specific: working_directory + args */}
        {stepType === "exec" && (
          <div style={{ display: "flex", flexDirection: "row", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <FormRow label="Working Directory">
                <input
                  value={step.working_directory || ""}
                  onChange={(e) => onChange({ working_directory: e.target.value || undefined })}
                  placeholder="/workspace"
                  style={inputStyle}
                  disabled={disabled}
                />
              </FormRow>
            </div>
            <div style={{ flex: 1 }}>
              <FormRow label="Arguments" description="Comma-separated">
                <input
                  value={(step.args || []).join(", ")}
                  onChange={(e) => onChange({ args: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                  placeholder="--verbose, --dry-run"
                  style={inputStyle}
                  disabled={disabled}
                />
              </FormRow>
            </div>
          </div>
        )}

        {/* Model override (agent only) */}
        {stepType === "agent" && (
          <FormRow label="Model Override" description="Leave empty to use workflow default">
            <LlmModelDropdown
              value={step.model || ""}
              onChange={(v) => onChange({ model: v || null })}
              placeholder="Use default"
              allowClear
            />
          </FormRow>
        )}

        {/* Timeout (agent + exec) */}
        {stepType !== "tool" && (
          <FormRow label="Timeout (seconds)">
            <input
              type="number"
              value={step.timeout ?? ""}
              onChange={(e) => onChange({ timeout: e.target.value ? (isNaN(parseInt(e.target.value)) ? null : parseInt(e.target.value)) : null })}
              placeholder="Use default"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>
        )}

        {/* Result truncation */}
        <FormRow label="Result Max Chars" description="Max chars to store from result">
          <input
            type="number"
            value={step.result_max_chars ?? ""}
            onChange={(e) => onChange({ result_max_chars: e.target.value ? (isNaN(parseInt(e.target.value)) ? null : parseInt(e.target.value)) : null })}
            placeholder="2000 (default)"
            style={inputStyle}
            disabled={disabled}
          />
        </FormRow>
      </FieldGroup>

      {/* Tools & Context group (agent only) */}
      {stepType === "agent" && (
        <FieldGroup title="Tools & Context" defaultOpen t={t}>
          <FormRow label="Tools" description="Comma-separated tool names">
            <input
              value={(step.tools || []).join(", ")}
              onChange={(e) => onChange({ tools: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="web_search, exec_command"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          <FormRow label="Capabilities" description="Comma-separated capability IDs">
            <input
              value={(step.carapaces || []).join(", ")}
              onChange={(e) => onChange({ carapaces: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="qa, code-review"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          <FormRow label="Secrets" description={workflowSecrets.length > 0 ? "Scope which workflow secrets this step can access" : "Add secrets at the workflow level first"}>
            <SecretChipPicker
              available={workflowSecrets}
              selected={step.secrets || []}
              onChange={(v) => onChange({ secrets: v })}
              disabled={disabled}
              t={t}
              emptyMessage="No secrets declared on this workflow."
            />
          </FormRow>

          <div style={{ display: "flex", flexDirection: "row", gap: 16, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 180 }}>
              <Toggle
                value={!!step.inject_prior_results}
                onChange={(v) => onChange({ inject_prior_results: v })}
                label={<span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 6 }}>Inject Prior Results <HelpTooltip text="Appends completed step results to this step's prompt context." /></span>}
                description="Include completed step results"
              />
            </div>
            {step.inject_prior_results && (
              <div style={{ flex: 1, minWidth: 180 }}>
                <FormRow label="Max Chars per Result">
                  <input
                    type="number"
                    value={step.prior_result_max_chars ?? ""}
                    onChange={(e) => onChange({ prior_result_max_chars: e.target.value ? (isNaN(parseInt(e.target.value)) ? null : parseInt(e.target.value)) : null })}
                    placeholder="500 (default)"
                    style={inputStyle}
                    disabled={disabled}
                  />
                </FormRow>
              </div>
            )}
          </div>
        </FieldGroup>
      )}

      {/* Control Flow group */}
      <FieldGroup title="Control Flow" defaultOpen={false} t={t}>
        {/* Approval + On Failure */}
        <div style={{ display: "flex", flexDirection: "row", gap: 16, flexWrap: "wrap" }}>
          {stepType !== "tool" && (
            <div style={{ flex: 1, minWidth: 180 }}>
              <Toggle
                value={!!step.requires_approval}
                onChange={(v) => onChange({ requires_approval: v })}
                label="Requires Approval"
                description="Pause until manually approved"
              />
            </div>
          )}
          <div style={{ flex: 1, minWidth: 180 }}>
            <FormRow label={<span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 6 }}>On Failure <HelpTooltip text={stepType === "tool" ? "abort: stop workflow. continue: marks failed but proceeds." : "abort: stop workflow. continue: marks failed but proceeds. retry:N: retries N times."} /></span>}>
              <select
                value={step.on_failure || "abort"}
                onChange={(e) => onChange({ on_failure: e.target.value })}
                style={{ ...inputStyle, cursor: "pointer" }}
                disabled={disabled}
              >
                <option value="abort">Abort workflow</option>
                <option value="continue">Continue to next step</option>
                {stepType !== "tool" && (
                  <>
                    <option value="retry:1">Retry (1 attempt)</option>
                    <option value="retry:2">Retry (2 attempts)</option>
                    <option value="retry:3">Retry (3 attempts)</option>
                  </>
                )}
              </select>
            </FormRow>
          </div>
        </div>

        {/* Condition */}
        <WorkflowConditionBuilder
          condition={step.when || null}
          onChange={(c) => onChange({ when: c })}
          priorStepIds={priorStepIds}
          disabled={!!disabled}
          t={t}
        />
      </FieldGroup>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible field group
// ---------------------------------------------------------------------------

function FieldGroup({ title, defaultOpen, children, t }: {
  title: string;
  defaultOpen: boolean;
  children: React.ReactNode;
  t: ThemeTokens;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div style={{
      borderRadius: 8,
      border: `1px solid ${t.surfaceBorder}`,
      background: t.surfaceRaised,
      overflow: "hidden",
    }}>
      <button type="button"
        onClick={() => setOpen(!open)}
        style={{
          flexDirection: "row", alignItems: "center", gap: 6,
          paddingBlock: 8, paddingInline: 12,
        }}
      >
        {open
          ? <ChevronDown size={12} color={t.textMuted} />
          : <ChevronRight size={12} color={t.textMuted} />
        }
        <span style={{
          fontSize: 11, fontWeight: 700, color: t.textMuted,
          textTransform: "uppercase", letterSpacing: 0.5,
        }}>
          {title}
        </span>
      </button>
      {open && (
        <div style={{
          padding: "4px 12px 12px",
          display: "flex", flexDirection: "column", gap: 12,
          borderTop: `1px solid ${t.surfaceBorder}`,
        }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool args JSON editor (moved from WorkflowStepEditor.tsx)
// ---------------------------------------------------------------------------

function ToolArgsEditor({ value, onChange, disabled, t, inputStyle }: {
  value: Record<string, any> | null | undefined;
  onChange: (v: Record<string, any>) => void;
  disabled?: boolean;
  t: ThemeTokens;
  inputStyle: React.CSSProperties;
}) {
  const [text, setText] = useState(value && Object.keys(value).length > 0 ? JSON.stringify(value, null, 2) : "");
  const [hasError, setHasError] = useState(false);

  // Sync external value changes — always update when value reference changes
  useEffect(() => {
    if (!value || (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)) {
      setText("");
      setHasError(false);
    } else {
      const canonical = JSON.stringify(value, null, 2);
      // Only update if text doesn't already parse to the same value
      if (hasError || text !== canonical) {
        try {
          const current = JSON.parse(text);
          if (JSON.stringify(current, null, 2) !== canonical) {
            setText(canonical);
            setHasError(false);
          }
        } catch {
          setText(canonical);
          setHasError(false);
        }
      }
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <textarea
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        if (!e.target.value.trim()) {
          onChange({});
          setHasError(false);
          return;
        }
        try {
          const parsed = JSON.parse(e.target.value);
          if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) {
            setHasError(true);
            return;
          }
          onChange(parsed);
          setHasError(false);
        } catch {
          setHasError(true);
        }
      }}
      placeholder={'{\n  "query": "{{search_term}}"\n}'}
      rows={3}
      style={{
        ...inputStyle,
        border: `1px solid ${hasError ? t.danger : t.inputBorder}`,
        fontFamily: "monospace", fontSize: 12,
        resize: "vertical" as const, minHeight: 60,
      }}
      disabled={disabled}
    />
  );
}

// ---------------------------------------------------------------------------
// Empty state for right pane
// ---------------------------------------------------------------------------

export function StepDetailEmptyState({ t }: { t: ThemeTokens }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      flex: 1, padding: 32, color: t.textDim,
    }}>
      <Bot size={28} color={t.surfaceBorder} />
      <span style={{ color: t.textDim, fontSize: 13, marginTop: 12, textAlign: "center" }}>
        Select a step from the list to edit its configuration.
      </span>
    </div>
  );
}
