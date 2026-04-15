/**
 * Left pane step navigator with compact step cards.
 * Handles step selection, add, remove, and reorder.
 */
import { useCallback } from "react";

import { type ThemeTokens } from "@/src/theme/tokens";
import { Plus, Bot, Zap, Terminal } from "lucide-react";
import type { WorkflowStep } from "@/src/types/api";
import { WorkflowStepCard } from "./WorkflowStepCard";

interface WorkflowStepListProps {
  steps: WorkflowStep[];
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
  onChange: (steps: WorkflowStep[]) => void;
  disabled?: boolean;
  t: ThemeTokens;
}

export function WorkflowStepList({
  steps, selectedIndex, onSelect, onChange, disabled, t,
}: WorkflowStepListProps) {
  const moveStep = useCallback((index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
    // Follow the moved step
    onSelect(target);
  }, [steps, onChange, onSelect]);

  const removeStep = useCallback((index: number) => {
    const next = steps.filter((_, i) => i !== index);
    onChange(next);
    // Adjust selection
    if (next.length === 0) {
      onSelect(null);
    } else if (selectedIndex === null) {
      // No selection — nothing to adjust
    } else if (selectedIndex === index) {
      // Removed the selected step — select the nearest
      onSelect(Math.min(index, next.length - 1));
    } else if (selectedIndex > index) {
      // Removed a step before the selected one — shift down
      onSelect(selectedIndex - 1);
    }
  }, [steps, onChange, selectedIndex, onSelect]);

  const addStep = useCallback((type: "agent" | "tool" | "exec" = "agent") => {
    const existingIds = new Set(steps.map((s) => s.id));
    let n = steps.length + 1;
    while (existingIds.has(`step_${n}`)) n++;
    const newStep: WorkflowStep = {
      id: `step_${n}`,
      type,
      prompt: type === "tool" ? undefined : "",
    };
    onChange([...steps, newStep]);
    onSelect(steps.length);
  }, [steps, onChange, onSelect]);

  return (
    <div style={{ gap: 4 }}>
      {/* Section header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
        padding: "4px 0",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, color: t.textMuted,
            textTransform: "uppercase", letterSpacing: 1,
          }}>
            Steps
          </span>
          <span style={{
            fontSize: 10, fontWeight: 600, color: t.textDim,
            background: t.surfaceRaised, borderRadius: 8,
            padding: "1px 6px",
          }}>
            {steps.length}
          </span>
        </div>
      </div>

      {/* Step cards */}
      {steps.map((step, i) => (
        <WorkflowStepCard
          key={`${step.id}-${i}`}
          step={step}
          index={i}
          isFirst={i === 0}
          isLast={i === steps.length - 1}
          selected={selectedIndex === i}
          onSelect={() => onSelect(i)}
          onMove={disabled ? undefined : (dir) => moveStep(i, dir)}
          onRemove={disabled ? undefined : () => removeStep(i)}
          disabled={disabled}
          t={t}
        />
      ))}

      {/* Empty state */}
      {steps.length === 0 && (
        <div style={{
          padding: "20px 12px", textAlign: "center",
          borderRadius: 8, border: `1px dashed ${t.surfaceBorder}`,
        }}>
          <span style={{ color: t.textDim, fontSize: 12 }}>
            No steps yet. Add one to get started.
          </span>
        </div>
      )}

      {/* Add step button with type picker */}
      {!disabled && (
        <AddStepButton onAdd={addStep} t={t} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add step button with inline type picker
// ---------------------------------------------------------------------------

function AddStepButton({ onAdd, t }: {
  onAdd: (type: "agent" | "tool" | "exec") => void;
  t: ThemeTokens;
}) {
  return (
    <div style={{
      display: "flex", flexDirection: "row", gap: 4, marginTop: 4,
    }}>
      <button type="button"
        onClick={() => onAdd("agent")}
        style={{
          flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
          gap: 4, paddingBlock: 7, borderRadius: 6,
          borderWidth: 1, borderStyle: "dashed", borderColor: t.accentBorder,
          backgroundColor: t.accentSubtle,
        }}
      >
        <Bot size={12} color={t.accent} />
        <span style={{ color: t.accent, fontSize: 11, fontWeight: "600" }}>Agent</span>
      </button>
      <button type="button"
        onClick={() => onAdd("tool")}
        style={{
          flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
          gap: 4, paddingBlock: 7, borderRadius: 6,
          borderWidth: 1, borderStyle: "dashed", borderColor: t.purpleBorder,
          backgroundColor: t.purpleSubtle,
        }}
      >
        <Zap size={12} color={t.purple} />
        <span style={{ color: t.purple, fontSize: 11, fontWeight: "600" }}>Tool</span>
      </button>
      <button type="button"
        onClick={() => onAdd("exec")}
        style={{
          flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
          gap: 4, paddingBlock: 7, borderRadius: 6,
          borderWidth: 1, borderStyle: "dashed", borderColor: t.warningBorder,
          backgroundColor: t.warningSubtle,
        }}
      >
        <Terminal size={12} color={t.warning} />
        <span style={{ color: t.warning, fontSize: 11, fontWeight: "600" }}>Exec</span>
      </button>
    </div>
  );
}
