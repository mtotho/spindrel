/**
 * Structured step editor for plans.
 * Adapted from ui/src/components/mission-control/StepListEditor.tsx for web.
 */
import { ShieldAlert, ArrowUp, ArrowDown, X, Plus } from "lucide-react";

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

export default function StepListEditor({ steps, onChange }: StepListEditorProps) {
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
    onChange([...steps, { key: makeStepKey(), content: "", requires_approval: false }]);
  };

  return (
    <div className="space-y-1.5">
      {steps.map((step, i) => (
        <div key={step.key} className="flex items-center gap-2">
          <span className="text-xs text-content-dim w-5 text-right font-mono">{i + 1}</span>
          <input
            type="text"
            value={step.content}
            onChange={(e) => updateStep(step.key, { content: e.target.value })}
            placeholder="Step description..."
            className="flex-1 bg-surface-1 border border-surface-3 rounded-md px-2.5 py-1.5 text-xs text-content placeholder-content-dim focus:outline-none focus:border-accent/40"
          />
          <button
            onClick={() => updateStep(step.key, { requires_approval: !step.requires_approval })}
            className="p-1 transition-opacity"
            style={{ opacity: step.requires_approval ? 1 : 0.3 }}
            title="Toggle approval gate"
          >
            <ShieldAlert size={14} color={step.requires_approval ? "#a855f7" : "#9ca3af"} />
          </button>
          <button
            onClick={() => moveStep(i, -1)}
            disabled={i === 0}
            className="p-1 disabled:opacity-20 opacity-60 hover:opacity-100 transition-opacity"
          >
            <ArrowUp size={13} className="text-content-muted" />
          </button>
          <button
            onClick={() => moveStep(i, 1)}
            disabled={i === steps.length - 1}
            className="p-1 disabled:opacity-20 opacity-60 hover:opacity-100 transition-opacity"
          >
            <ArrowDown size={13} className="text-content-muted" />
          </button>
          <button
            onClick={() => removeStep(step.key)}
            disabled={steps.length <= 1}
            className="p-1 disabled:opacity-20 opacity-60 hover:opacity-100 transition-opacity"
          >
            <X size={13} color="#ef4444" />
          </button>
        </div>
      ))}
      <button
        onClick={addStep}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-content-muted bg-surface-1 border border-surface-3 rounded-md hover:text-content transition-colors mt-1"
      >
        <Plus size={12} />
        Add Step
      </button>
    </div>
  );
}
