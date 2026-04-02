/**
 * Visual step editor for workflow definitions.
 * Replaces JSON textarea with expandable step cards.
 */
import { useState, useCallback } from "react";
import { View, Text, Pressable } from "react-native";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FormRow, Toggle } from "@/src/components/shared/FormControls";
import {
  ChevronDown, ChevronRight, ArrowUp, ArrowDown, X, Plus,
  ShieldAlert, GitBranch, RotateCcw,
} from "lucide-react";
import type { WorkflowStep } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WorkflowStepEditorProps {
  steps: WorkflowStep[];
  onChange: (steps: WorkflowStep[]) => void;
  disabled?: boolean;
  /** List of prior step IDs for condition builder dropdowns */
  allStepIds?: string[];
}

// ---------------------------------------------------------------------------
// Main editor
// ---------------------------------------------------------------------------

export function WorkflowStepEditor({ steps, onChange, disabled }: WorkflowStepEditorProps) {
  const t = useThemeTokens();
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  const updateStep = useCallback((index: number, patch: Partial<WorkflowStep>) => {
    const next = steps.map((s, i) => (i === index ? { ...s, ...patch } : s));
    onChange(next);
  }, [steps, onChange]);

  const removeStep = useCallback((index: number) => {
    onChange(steps.filter((_, i) => i !== index));
  }, [steps, onChange]);

  const moveStep = useCallback((index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    // Update expanded index to follow the moved step
    if (expandedIdx === index) setExpandedIdx(target);
    else if (expandedIdx === target) setExpandedIdx(index);
    onChange(next);
  }, [steps, onChange, expandedIdx]);

  const addStep = useCallback(() => {
    const newId = `step_${steps.length + 1}`;
    const newStep: WorkflowStep = {
      id: newId,
      prompt: "",
    };
    onChange([...steps, newStep]);
    setExpandedIdx(steps.length);
  }, [steps, onChange]);

  return (
    <View style={{ gap: 6 }}>
      {steps.map((step, i) => (
        <StepCard
          key={`${step.id}-${i}`}
          step={step}
          index={i}
          isFirst={i === 0}
          isLast={i === steps.length - 1}
          expanded={expandedIdx === i}
          onToggle={() => setExpandedIdx(expandedIdx === i ? null : i)}
          onChange={(patch) => updateStep(i, patch)}
          onRemove={() => removeStep(i)}
          onMove={(dir) => moveStep(i, dir)}
          disabled={!!disabled}
          priorStepIds={steps.slice(0, i).map((s) => s.id)}
          t={t}
        />
      ))}
      {!disabled && (
        <Pressable
          onPress={addStep}
          style={{
            flexDirection: "row", alignItems: "center", gap: 6,
            paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
            borderWidth: 1, borderStyle: "dashed", borderColor: t.surfaceBorder,
            justifyContent: "center",
          }}
        >
          <Plus size={14} color={t.textMuted} />
          <Text style={{ color: t.textMuted, fontSize: 13 }}>Add Step</Text>
        </Pressable>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Step card
// ---------------------------------------------------------------------------

interface StepCardProps {
  step: WorkflowStep;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  expanded: boolean;
  onToggle: () => void;
  onChange: (patch: Partial<WorkflowStep>) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  disabled: boolean;
  priorStepIds: string[];
  t: ThemeTokens;
}

function StepCard({
  step, index, isFirst, isLast, expanded, onToggle,
  onChange, onRemove, onMove, disabled, priorStepIds, t,
}: StepCardProps) {
  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 13, width: "100%", outline: "none",
    opacity: disabled ? 0.6 : 1,
  };

  return (
    <div style={{
      borderRadius: 10,
      border: `1px solid ${expanded ? t.accentBorder : t.surfaceBorder}`,
      background: t.surfaceRaised,
      overflow: "hidden",
    }}>
      {/* Collapsed header */}
      <div
        onClick={onToggle}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px", cursor: "pointer",
          userSelect: "none",
        }}
      >
        {expanded
          ? <ChevronDown size={14} color={t.textDim} />
          : <ChevronRight size={14} color={t.textDim} />
        }
        <span style={{
          width: 22, height: 22, borderRadius: 11, flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          fontSize: 11, fontWeight: 700, color: t.accent,
        }}>
          {index + 1}
        </span>
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, minWidth: 0 }}>
          {step.id || `step_${index}`}
        </span>
        <span style={{
          flex: 1, fontSize: 12, color: t.textDim,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {!expanded && step.prompt ? `\u2014 ${step.prompt.slice(0, 80)}` : ""}
        </span>

        {/* Badges */}
        <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
          {step.requires_approval && <Badge t={t} bg={t.warningSubtle} border={t.warningBorder} color={t.warning} icon={<ShieldAlert size={10} />} text="approval" />}
          {step.when && Object.keys(step.when).length > 0 && <Badge t={t} bg={t.purpleSubtle} border={t.purpleBorder} color={t.purple} icon={<GitBranch size={10} />} text="conditional" />}
          {step.on_failure && step.on_failure.startsWith("retry:") && <Badge t={t} bg={t.codeBg} border={t.surfaceBorder} color={t.textMuted} icon={<RotateCcw size={10} />} text={step.on_failure} />}
        </div>

        {/* Action buttons */}
        {!disabled && (
          <div style={{ display: "flex", gap: 2, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
            <IconBtn onClick={() => onMove(-1)} disabled={isFirst} t={t}><ArrowUp size={12} /></IconBtn>
            <IconBtn onClick={() => onMove(1)} disabled={isLast} t={t}><ArrowDown size={12} /></IconBtn>
            <IconBtn onClick={onRemove} t={t}><X size={12} /></IconBtn>
          </div>
        )}
      </div>

      {/* Expanded form */}
      {expanded && (
        <div style={{
          padding: "12px 16px", paddingTop: 4,
          borderTop: `1px solid ${t.surfaceBorder}`,
          display: "flex", flexDirection: "column", gap: 14,
        }}>
          {/* ID */}
          <FormRow label="Step ID">
            <input
              value={step.id}
              onChange={(e) => onChange({ id: e.target.value })}
              placeholder="step_1"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Prompt */}
          <FormRow label="Prompt" description="Use {{param}} for params, {{steps.id.result}} for prior results">
            <textarea
              value={step.prompt}
              onChange={(e) => onChange({ prompt: e.target.value })}
              placeholder="Execute the task..."
              rows={4}
              style={{
                ...inputStyle, fontFamily: "monospace", fontSize: 12,
                resize: "vertical" as const, minHeight: 80,
              }}
              disabled={disabled}
            />
          </FormRow>

          {/* Two column row: approval + on_failure */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 180 }}>
              <Toggle
                value={!!step.requires_approval}
                onChange={(v) => onChange({ requires_approval: v })}
                label="Requires Approval"
                description="Pause workflow until manually approved"
              />
            </div>
            <div style={{ flex: 1, minWidth: 180 }}>
              <FormRow label="On Failure">
                <select
                  value={step.on_failure || "abort"}
                  onChange={(e) => onChange({ on_failure: e.target.value })}
                  style={{ ...inputStyle, cursor: "pointer" }}
                  disabled={disabled}
                >
                  <option value="abort">Abort workflow</option>
                  <option value="continue">Continue to next step</option>
                  <option value="retry:1">Retry (1 attempt)</option>
                  <option value="retry:2">Retry (2 attempts)</option>
                  <option value="retry:3">Retry (3 attempts)</option>
                </select>
              </FormRow>
            </div>
          </div>

          {/* Tools */}
          <FormRow label="Tools" description="Comma-separated tool names">
            <input
              value={(step.tools || []).join(", ")}
              onChange={(e) => onChange({ tools: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="web_search, exec_command"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Carapaces */}
          <FormRow label="Carapaces" description="Comma-separated carapace IDs">
            <input
              value={(step.carapaces || []).join(", ")}
              onChange={(e) => onChange({ carapaces: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="qa, code-review"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Model override */}
          <FormRow label="Model Override" description="Leave empty to use workflow default">
            <LlmModelDropdown
              value={step.model || ""}
              onChange={(v) => onChange({ model: v || null })}
              placeholder="Use default"
              allowClear
            />
          </FormRow>

          {/* Timeout */}
          <FormRow label="Timeout (seconds)">
            <input
              type="number"
              value={step.timeout ?? ""}
              onChange={(e) => onChange({ timeout: e.target.value ? parseInt(e.target.value) : null })}
              placeholder="Use default"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Secrets */}
          <FormRow label="Secrets" description="Comma-separated (subset of workflow secrets)">
            <input
              value={(step.secrets || []).join(", ")}
              onChange={(e) => onChange({ secrets: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
              placeholder="API_KEY"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Prior result injection */}
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 180 }}>
              <Toggle
                value={!!step.inject_prior_results}
                onChange={(v) => onChange({ inject_prior_results: v })}
                label="Inject Prior Results"
                description="Include completed step results in this step's context"
              />
            </div>
            {step.inject_prior_results && (
              <div style={{ flex: 1, minWidth: 180 }}>
                <FormRow label="Max Chars per Result">
                  <input
                    type="number"
                    value={step.prior_result_max_chars ?? ""}
                    onChange={(e) => onChange({ prior_result_max_chars: e.target.value ? parseInt(e.target.value) : null })}
                    placeholder="500 (default)"
                    style={inputStyle}
                    disabled={disabled}
                  />
                </FormRow>
              </div>
            )}
          </div>

          {/* Result truncation */}
          <FormRow label="Result Max Chars" description="Max chars to store from this step's result">
            <input
              type="number"
              value={step.result_max_chars ?? ""}
              onChange={(e) => onChange({ result_max_chars: e.target.value ? parseInt(e.target.value) : null })}
              placeholder="2000 (default)"
              style={inputStyle}
              disabled={disabled}
            />
          </FormRow>

          {/* Condition (when) */}
          <ConditionEditor
            condition={step.when || null}
            onChange={(c) => onChange({ when: c })}
            priorStepIds={priorStepIds}
            disabled={disabled}
            t={t}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Condition editor (simple + advanced mode)
// ---------------------------------------------------------------------------

function ConditionEditor({
  condition, onChange, priorStepIds, disabled, t,
}: {
  condition: Record<string, any> | null;
  onChange: (c: Record<string, any> | null) => void;
  priorStepIds: string[];
  disabled: boolean;
  t: ThemeTokens;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [jsonText, setJsonText] = useState(condition ? JSON.stringify(condition, null, 2) : "");

  // Detect if current condition is a simple step+status check
  const isSimple = condition && "step" in condition && "status" in condition
    && Object.keys(condition).length === 2;

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 8, padding: "8px 12px", color: t.inputText,
    fontSize: 13, outline: "none",
    opacity: disabled ? 0.6 : 1,
  };

  if (advanced || (condition && !isSimple && Object.keys(condition).length > 0)) {
    return (
      <FormRow label="When (Condition)">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <textarea
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                onChange(parsed);
              } catch {
                // Don't update until valid JSON
              }
            }}
            placeholder='{"step": "step_1", "status": "done"}'
            rows={3}
            style={{
              ...inputStyle, fontFamily: "monospace", fontSize: 12,
              resize: "vertical" as const, width: "100%",
            }}
            disabled={disabled}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              onClick={() => { setAdvanced(false); }}
              style={{
                background: "none", border: "none", color: t.accent,
                fontSize: 11, cursor: "pointer", padding: 0,
              }}
            >
              Simple mode
            </button>
            {condition && Object.keys(condition).length > 0 && (
              <button
                onClick={() => { onChange(null); setJsonText(""); }}
                style={{
                  background: "none", border: "none", color: t.textDim,
                  fontSize: 11, cursor: "pointer", padding: 0,
                }}
              >
                Clear condition
              </button>
            )}
          </div>
        </div>
      </FormRow>
    );
  }

  // Simple mode
  const stepId = (isSimple && condition?.step) || "";
  const stepStatus = (isSimple && condition?.status) || "done";

  return (
    <FormRow label="When (Condition)" description="Only run this step if a prior step has a specific status">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={stepId}
          onChange={(e) => {
            const val = e.target.value;
            if (val) {
              const c = { step: val, status: stepStatus || "done" };
              onChange(c);
              setJsonText(JSON.stringify(c, null, 2));
            } else {
              onChange(null);
              setJsonText("");
            }
          }}
          style={{ ...inputStyle, flex: 1, minWidth: 120, cursor: "pointer" }}
          disabled={disabled}
        >
          <option value="">Always run (no condition)</option>
          {priorStepIds.map((sid) => (
            <option key={sid} value={sid}>{sid}</option>
          ))}
        </select>
        {stepId && (
          <select
            value={stepStatus}
            onChange={(e) => {
              const c = { step: stepId, status: e.target.value };
              onChange(c);
              setJsonText(JSON.stringify(c, null, 2));
            }}
            style={{ ...inputStyle, width: 100, cursor: "pointer" }}
            disabled={disabled}
          >
            <option value="done">done</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
        )}
        <button
          onClick={() => setAdvanced(true)}
          style={{
            background: "none", border: "none", color: t.accent,
            fontSize: 11, cursor: "pointer", padding: 0,
          }}
        >
          Advanced
        </button>
      </div>
    </FormRow>
  );
}

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

function Badge({ t, bg, border, color, icon, text }: {
  t: ThemeTokens; bg: string; border: string; color: string;
  icon?: React.ReactNode; text: string;
}) {
  return (
    <span style={{
      fontSize: 10, padding: "1px 5px", borderRadius: 3,
      background: bg, border: `1px solid ${border}`, color,
      display: "inline-flex", alignItems: "center", gap: 3,
      whiteSpace: "nowrap",
    }}>
      {icon}{text}
    </span>
  );
}

function IconBtn({ onClick, disabled, children, t }: {
  onClick: () => void; disabled?: boolean; children: React.ReactNode; t: ThemeTokens;
}) {
  return (
    <Pressable
      onPress={onClick}
      disabled={disabled}
      style={{
        padding: 4, borderRadius: 4,
        opacity: disabled ? 0.3 : 0.7,
      }}
    >
      <Text style={{ color: t.textDim }}>{children}</Text>
    </Pressable>
  );
}
