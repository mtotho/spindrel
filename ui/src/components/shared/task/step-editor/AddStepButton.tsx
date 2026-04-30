import { useState } from "react";
import { Plus } from "lucide-react";
import type { StepType } from "@/src/api/hooks/useTasks";
import { visibleStepTypes } from "../TaskStepEditorModel";

export function AddStepButton({ onAdd, machineStepTypes = [] }: { onAdd: (type: StepType) => void; machineStepTypes?: StepType[] }) {
  const [open, setOpen] = useState(false);
  const stepTypes = visibleStepTypes(machineStepTypes);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-text-muted bg-transparent border border-transparent rounded-md cursor-pointer hover:bg-accent/[0.08] hover:text-accent transition-colors"
      >
        <Plus size={14} />
        Add Step
      </button>
    );
  }

  return (
    <div className="flex flex-row items-center gap-1.5">
      {stepTypes.map((t) => {
        const TIcon = t.icon;
        return (
          <button
            key={t.value}
            onClick={() => { onAdd(t.value); setOpen(false); }}
            className="flex flex-row items-center gap-1.5 px-3.5 py-2 text-xs font-medium bg-surface-raised/60 rounded-md cursor-pointer text-text hover:bg-surface-overlay/60 hover:text-accent transition-colors"
          >
            <TIcon size={14} className={t.color} />
            {t.label}
          </button>
        );
      })}
      <button
        onClick={() => setOpen(false)}
        className="px-2.5 py-2 text-xs text-text-dim bg-transparent border-none cursor-pointer hover:text-text"
      >
        Cancel
      </button>
    </div>
  );
}
