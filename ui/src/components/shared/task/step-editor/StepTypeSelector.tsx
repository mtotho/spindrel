import type { StepType } from "@/src/api/hooks/useTasks";
import { SelectDropdown } from "../../SelectDropdown";
import { STEP_TYPES, isKnownStepType, stepMeta } from "../TaskStepEditorModel";

export const ON_FAILURE_OPTIONS = [
  { value: "abort", label: "Stop on fail" },
  { value: "continue", label: "Continue on fail" },
];

export function StepTypeSelector({ value, onChange }: { value: StepType; onChange: (v: StepType) => void }) {
  const meta = stepMeta(value);
  const Icon = meta.icon;

  return (
    <div className="w-[126px] shrink-0">
      <SelectDropdown
        value={value}
        options={STEP_TYPES.map((stepType) => {
          const StepIcon = stepType.icon;
          return {
            value: stepType.value,
            label: stepType.label,
            icon: <StepIcon size={12} className={stepType.color} />,
          };
        })}
        onChange={(next) => {
          if (isKnownStepType(next)) onChange(next);
        }}
        size="compact"
        popoverWidth="content"
        renderValue={() => (
          <span className="inline-flex min-w-0 items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider">
            <Icon size={11} />
            <span className="truncate">{meta.label}</span>
          </span>
        )}
        triggerClassName={`min-h-[26px] rounded-md border-transparent px-2.5 ${meta.bgBadge} hover:bg-surface-overlay/60`}
      />
    </div>
  );
}
