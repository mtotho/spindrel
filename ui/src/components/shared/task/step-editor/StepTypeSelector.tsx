import type { StepType } from "@/src/api/hooks/useTasks";
import { SelectDropdown } from "../../SelectDropdown";
import { isKnownStepType, stepMeta, visibleStepTypes } from "../TaskStepEditorModel";

export const ON_FAILURE_OPTIONS = [
  { value: "abort", label: "Stop on fail" },
  { value: "continue", label: "Continue on fail" },
];

export function StepTypeSelector({ value, onChange, machineStepTypes = [] }: { value: StepType; onChange: (v: StepType) => void; machineStepTypes?: StepType[] }) {
  const meta = stepMeta(value);
  const Icon = meta.icon;
  const visibleTypes = visibleStepTypes(machineStepTypes);
  const options = visibleTypes.some((stepType) => stepType.value === value)
    ? visibleTypes
    : [...visibleTypes, meta];

  return (
    <div className="shrink-0">
      <SelectDropdown
        value={value}
        options={options.map((stepType) => {
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
