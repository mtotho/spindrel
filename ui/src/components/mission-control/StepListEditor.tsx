import { useThemeTokens } from "@/src/theme/tokens";
import { ShieldAlert, ArrowUp, ArrowDown, X, Plus, GripVertical } from "lucide-react";

export interface StepDraft {
  key: string;
  content: string;
  requires_approval: boolean;
}

let nextKey = 1;
export function makeStepKey(): string {
  return `step-${nextKey++}-${Math.random().toString(36).slice(2, 6)}`;
}

interface StepListEditorProps {
  steps: StepDraft[];
  onChange: (steps: StepDraft[]) => void;
}

export function StepListEditor({ steps, onChange }: StepListEditorProps) {
  const t = useThemeTokens();

  const updateStep = (key: string, field: Partial<StepDraft>) => {
    onChange(steps.map((s) => (s.key === key ? { ...s, ...field } : s)));
  };

  const removeStep = (key: string) => {
    if (steps.length <= 1) return;
    onChange(steps.filter((s) => s.key !== key));
  };

  const moveStep = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const addStep = () => {
    onChange([
      ...steps,
      { key: makeStepKey(), content: "", requires_approval: false },
    ]);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div
        style={{
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.codeBg,
          overflow: "hidden",
        }}
      >
        {steps.map((step, i) => (
          <div
            key={step.key}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              borderBottom: i < steps.length - 1 ? `1px solid ${t.surfaceBorder}` : "none",
            }}
          >
            {/* Grip + number */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 2,
                flexShrink: 0,
              }}
            >
              <GripVertical size={11} color={t.textDim} style={{ opacity: 0.4 }} />
              <span
                style={{
                  fontSize: 11,
                  color: t.textDim,
                  fontFamily: "monospace",
                  width: 16,
                  textAlign: "right",
                }}
              >
                {i + 1}
              </span>
            </div>

            {/* Content input */}
            <input
              type="text"
              value={step.content}
              onChange={(e) => updateStep(step.key, { content: e.target.value })}
              placeholder="Describe this step..."
              style={{
                flex: 1,
                fontSize: 13,
                color: t.text,
                backgroundColor: "transparent",
                border: "none",
                borderBottom: `1px solid transparent`,
                padding: "4px 0",
                outline: "none",
                fontFamily: "inherit",
                lineHeight: 1.4,
              }}
              onFocus={(e) => {
                (e.target as HTMLInputElement).style.borderBottomColor = t.accent;
              }}
              onBlur={(e) => {
                (e.target as HTMLInputElement).style.borderBottomColor = "transparent";
              }}
            />

            {/* Approval gate toggle */}
            <button
              onClick={() =>
                updateStep(step.key, {
                  requires_approval: !step.requires_approval,
                })
              }
              title={step.requires_approval ? "Approval gate enabled" : "Add approval gate"}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 3,
                padding: "2px 6px",
                borderRadius: 4,
                border: "none",
                background: step.requires_approval ? "rgba(168,85,247,0.08)" : "transparent",
                cursor: "pointer",
                opacity: step.requires_approval ? 1 : 0.3,
                transition: "opacity 0.15s, background 0.15s",
              }}
            >
              <ShieldAlert
                size={13}
                color={step.requires_approval ? "#a855f7" : t.textDim}
              />
              {step.requires_approval && (
                <span style={{ fontSize: 10, fontWeight: 600, color: "#a855f7" }}>Gate</span>
              )}
            </button>

            {/* Reorder buttons */}
            <div style={{ display: "flex", gap: 0 }}>
              <button
                onClick={() => moveStep(i, -1)}
                disabled={i === 0}
                style={{
                  background: "none",
                  border: "none",
                  cursor: i === 0 ? "default" : "pointer",
                  padding: 3,
                  opacity: i === 0 ? 0.15 : 0.5,
                  display: "flex",
                }}
              >
                <ArrowUp size={12} color={t.textDim} />
              </button>
              <button
                onClick={() => moveStep(i, 1)}
                disabled={i === steps.length - 1}
                style={{
                  background: "none",
                  border: "none",
                  cursor: i === steps.length - 1 ? "default" : "pointer",
                  padding: 3,
                  opacity: i === steps.length - 1 ? 0.15 : 0.5,
                  display: "flex",
                }}
              >
                <ArrowDown size={12} color={t.textDim} />
              </button>
            </div>

            {/* Delete */}
            <button
              onClick={() => removeStep(step.key)}
              disabled={steps.length <= 1}
              style={{
                background: "none",
                border: "none",
                cursor: steps.length <= 1 ? "default" : "pointer",
                padding: 3,
                opacity: steps.length <= 1 ? 0.15 : 0.5,
                display: "flex",
              }}
            >
              <X size={12} color="#ef4444" />
            </button>
          </div>
        ))}
      </div>

      {/* Add step button */}
      <button
        onClick={addStep}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          alignSelf: "flex-start",
          padding: "5px 12px",
          borderRadius: 6,
          border: `1px dashed ${t.surfaceBorder}`,
          background: "transparent",
          color: t.textDim,
          fontSize: 12,
          cursor: "pointer",
          marginTop: 2,
          transition: "border-color 0.15s, color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = t.textDim;
          (e.currentTarget as HTMLButtonElement).style.color = t.text;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor = t.surfaceBorder;
          (e.currentTarget as HTMLButtonElement).style.color = t.textDim;
        }}
      >
        <Plus size={12} />
        Add Step
      </button>
    </div>
  );
}
