import type { StepDef } from "@/src/api/hooks/useTasks";
import { MiniDropdown } from "./MiniDropdown";

type ConditionMode = "always" | "output_contains" | "output_not_contains" | "status_is";

const CONDITION_OPTIONS: { value: ConditionMode; label: string }[] = [
  { value: "always", label: "Always" },
  { value: "output_contains", label: "If prev output contains" },
  { value: "output_not_contains", label: "If prev output NOT contains" },
  { value: "status_is", label: "If prev step status is" },
];

const STATUS_OPTIONS = [
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
];

export function parseConditionMode(when: StepDef["when"]): { mode: ConditionMode; value: string } {
  if (!when) return { mode: "always", value: "" };
  if (when.output_contains) return { mode: "output_contains", value: when.output_contains };
  if (when.output_not_contains) return { mode: "output_not_contains", value: when.output_not_contains };
  if (when.status) return { mode: "status_is", value: when.status };
  return { mode: "always", value: "" };
}

export function buildCondition(mode: ConditionMode, value: string, prevStepId: string): StepDef["when"] {
  if (mode === "always") return null;
  const base: Record<string, any> = { step: prevStepId };
  if (mode === "output_contains") base.output_contains = value;
  else if (mode === "output_not_contains") base.output_not_contains = value;
  else if (mode === "status_is") base.status = value;
  return base;
}

export function StepConditionEditor({ step, stepIndex, steps, onChange }: {
  step: StepDef;
  stepIndex: number;
  steps: StepDef[];
  onChange: (when: StepDef["when"]) => void;
}) {
  const { mode, value } = parseConditionMode(step.when);
  const prevStep = stepIndex > 0 ? steps[stepIndex - 1] : null;
  const prevStepId = prevStep?.id ?? "step_0";

  if (stepIndex === 0) return null;

  return (
    <div className="flex flex-row items-center gap-2 text-xs flex-wrap">
      <span className="text-text-dim shrink-0">Run</span>
      <MiniDropdown
        value={mode}
        options={CONDITION_OPTIONS}
        onChange={(m) => {
          onChange(buildCondition(m as ConditionMode, m === "status_is" ? "done" : "", prevStepId));
        }}
      />
      {(mode === "output_contains" || mode === "output_not_contains") && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(buildCondition(mode, e.target.value, prevStepId))}
          placeholder="text to match..."
          className="bg-input border border-surface-border rounded-md px-2 py-1 text-text text-xs outline-none flex-1 min-w-[100px] focus:border-accent/40"
        />
      )}
      {mode === "status_is" && (
        <MiniDropdown
          value={value || "done"}
          options={STATUS_OPTIONS}
          onChange={(v) => onChange(buildCondition(mode, v, prevStepId))}
        />
      )}
    </div>
  );
}
